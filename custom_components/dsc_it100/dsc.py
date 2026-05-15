"""
DSC PC5401 RS-232 protocol library.

Translated from the Misterhouse `DSC5401.pm` Perl module by Jocelyn Brouillard
and Gaetan Lord. Uses the `serialx` async serial library (HA 2026.5+).

Frame format
────────────
Every frame on the wire is:

    <3-digit code><variable data><2 hex checksum bytes>\r\n

The checksum is the low byte of the sum of all ASCII bytes in
`<code> + <data>`, expressed as uppercase hex.

Outbound commands use the same format. The library handles framing,
checksums, and parsing; higher-level dispatching lives in the coordinator.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import serialx

_LOGGER = logging.getLogger(__name__)

# Serial parameters per the PC5401 spec
BYTE_SIZE = 8
PARITY = "N"
STOP_BITS = 1
DEFAULT_BAUDRATE = 9600

# Frame terminator on the wire
TERMINATOR = b"\r\n"

# Type alias for inbound-frame callback: (code: str, data: str) -> None
FrameCallback = Callable[[str, str], Awaitable[None] | None]


def checksum(payload: str) -> str:
    """Return the two-character uppercase hex checksum for `payload`.

    The DSC checksum is the low byte of the sum of the ASCII values of every
    character in the code + data portion of the frame (i.e. everything
    *except* the trailing checksum itself).
    """
    total = sum(payload.encode("ascii"))
    return f"{total & 0xFF:02X}"


def build_frame(code: str, data: str = "") -> bytes:
    """Build a complete wire frame for the given code and data.

    Frame = <code><data><checksum>\r\n
    """
    payload = f"{code}{data}"
    return f"{payload}{checksum(payload)}\r\n".encode("ascii")


def verify_frame(frame: str) -> tuple[str, str] | None:
    """Validate checksum and split into (code, data).

    Returns `None` if the frame is malformed or the checksum is wrong.
    `frame` should already have its trailing `\\r\\n` stripped.
    """
    if len(frame) < 5:
        return None
    code = frame[:3]
    cks_sent = frame[-2:].upper()
    payload = frame[:-2]
    if checksum(payload) != cks_sent:
        return None
    data = frame[3:-2]
    return code, data


class DSCIT100Connection:
    """Async serial connection to a DSC PC5401 interface.

    Opens a serialx connection, reads frames in a background task, validates
    each frame's checksum, and dispatches `(code, data)` tuples to a single
    registered callback.

    Lifecycle:
        conn = DSCIT100Connection(port, baudrate, on_frame, debug=False)
        await conn.connect()
        ...
        await conn.send("000")          # poll
        await conn.send("010", "1234012600")  # set datetime
        ...
        await conn.disconnect()
    """

    def __init__(
        self,
        port: str,
        baudrate: int = DEFAULT_BAUDRATE,
        on_frame: FrameCallback | None = None,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._on_frame = on_frame

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task | None = None
        self._write_lock = asyncio.Lock()
        self._closed = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open the serial port and start the read loop."""
        self._reader, self._writer = await serialx.open_serial_connection(
            self._port,
            baudrate=self._baudrate,
            byte_size=BYTE_SIZE,
            parity=PARITY,
            stopbits=STOP_BITS,
        )
        self._closed = False
        _LOGGER.info("DSC IT-100 connected on %s @ %d baud", self._port, self._baudrate)
        self._read_task = asyncio.ensure_future(self._read_loop())

        # Send a Poll first — the Perl module notes the first command often
        # produces a syntax error from stray serial bits, so warm up with a
        # NOP before doing anything that matters.
        try:
            await self.send("000")
            await asyncio.sleep(0.25)
            await self.send("001")   # initial StatusReport
        except OSError as exc:
            _LOGGER.warning("DSC IT-100 initial poll failed: %s", exc)

    async def disconnect(self) -> None:
        """Stop the read loop and close the port."""
        self._closed = True
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        _LOGGER.info("DSC IT-100 disconnected")

    # ── Send ─────────────────────────────────────────────────────────────────

    async def send(self, code: str, data: str = "") -> None:
        """Send a single command frame to the panel.

        Caller passes the 3-digit numeric code (e.g. "000" for Poll, "010" for
        SetDateTime) and any required data. Checksum and framing are added.
        """
        if not self._writer:
            raise RuntimeError("DSC IT-100 not connected")
        frame = build_frame(code, data)
        async with self._write_lock:
            _LOGGER.debug("DSC IT-100 TX raw: %r", frame)
            self._writer.write(frame)
            try:
                await self._writer.drain()
            except OSError as exc:
                _LOGGER.error("DSC IT-100 write failed: %s", exc)
                raise

    # ── Receive ──────────────────────────────────────────────────────────────

    async def _read_loop(self) -> None:
        """Background task: read frames, verify, dispatch."""
        assert self._reader is not None
        buf = b""
        try:
            while not self._closed:
                chunk = await self._reader.read(256)
                if not chunk:
                    # EOF — port closed underneath us
                    _LOGGER.warning("DSC IT-100 serial port closed by peer")
                    break

                # Debug mode (logger set to DEBUG) → log every raw chunk
                # exactly as received from the serial port.
                _LOGGER.debug("DSC IT-100 RX raw: %r", chunk)

                buf += chunk
                while TERMINATOR in buf:
                    line, buf = buf.split(TERMINATOR, 1)
                    if line:
                        await self._handle_line(line)
        except asyncio.CancelledError:
            pass
        except OSError as exc:
            _LOGGER.error("DSC IT-100 serial I/O error: %s", exc)

    async def _handle_line(self, line: bytes) -> None:
        """Decode, verify checksum, dispatch a single frame."""
        try:
            frame = line.decode("ascii", errors="ignore").strip()
        except UnicodeDecodeError:
            _LOGGER.warning("DSC IT-100 non-ascii frame: %r", line)
            return
        if not frame:
            return

        result = verify_frame(frame)
        if result is None:
            _LOGGER.warning("DSC IT-100 invalid frame or checksum: %r", frame)
            return

        code, data = result
        if self._on_frame:
            try:
                ret = self._on_frame(code, data)
                if asyncio.iscoroutine(ret):
                    await ret
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "DSC IT-100 frame handler raised for code=%s data=%r", code, data
                )

    # ── Convenience commands ─────────────────────────────────────────────────

    async def poll(self) -> None:
        """Send a Poll (NOP) command."""
        await self.send("000")

    async def status_report(self) -> None:
        """Request a full status report from the panel."""
        await self.send("001")

    async def set_clock(
        self,
        hour: int,
        minute: int,
        month: int,
        day: int,
        year_2digit: int,
    ) -> None:
        """Set the panel's internal date and time.

        DSC API command 010 expects the data field as HHMMmmDDYY (no
        separators), each zero-padded to 2 digits.
        """
        data = f"{hour:02d}{minute:02d}{month:02d}{day:02d}{year_2digit:02d}"
        await self.send("010", data)

