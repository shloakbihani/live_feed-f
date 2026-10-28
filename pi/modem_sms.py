"""SMS through a Quectel EC200U-CN on the Pi GPIO UART.

The Type-C cable only powers the module. AT commands use /dev/ttyAMA0,
which is UART0 from dtoverlay=uart0-pi5:

  module TXD -> Pi pin 10 (GPIO 15, RXD)
  module RXD -> Pi pin 8  (GPIO 14, TXD)

USB serial devices (/dev/ttyUSB*, /dev/ttyACM*) are never opened.
"""

from __future__ import annotations

import fcntl
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import serial

# Pi 5 GPIO UART. Not /dev/serial0, which is the console on ttyAMA10.
GPIO_UART = "/dev/ttyAMA0"

_LOCK_PATH = Path(__file__).parent / "logs" / "modem.lock"
_lock_depth = 0
_lock_file = None


@dataclass
class SmsSendResult:
    to: str
    ok: bool
    error: str | None = None


@contextmanager
def modem_lock(blocking: bool = True, timeout: float = 30):
    """One AT conversation at a time, including across processes.

    The keepalive and an SMS send share the GPIO UART. A second
    exclusive lock in this process is allowed so send_text can call
    find_port while it already holds the lock.
    """
    global _lock_depth, _lock_file
    acquired = False
    if _lock_depth == 0:
        _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fh = open(_LOCK_PATH, "a+")
        deadline = time.time() + timeout
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if not blocking or time.time() >= deadline:
                    fh.close()
                    raise TimeoutError("modem is busy")
                time.sleep(0.1)
        _lock_file = fh
        acquired = True
    _lock_depth += 1
    try:
        yield
    finally:
        _lock_depth -= 1
        if acquired and _lock_file is not None:
            fcntl.flock(_lock_file, fcntl.LOCK_UN)
            _lock_file.close()
            _lock_file = None


class ModemSms:
    def __init__(self, port: str = "", baud: int = 115200, sim_pin: str = ""):
        self.port = self._gpio_uart(port)
        self.baud = baud
        self.sim_pin = (sim_pin or "").strip()
        self._phase = "idle"
        self._at_port: str | None = None
        self._seen_ready = False
        self._last_ok = 0.0

    def candidates(self) -> list[str]:
        return [self.port] if Path(self.port).exists() else []

    @staticmethod
    def _gpio_uart(port: str) -> str:
        chosen = (port or "").strip() or GPIO_UART
        name = Path(chosen).name
        if name.startswith(("ttyUSB", "ttyACM")) or name == "ttyAMA10":
            return GPIO_UART
        return chosen

    def _log(self, message: str) -> None:
        print(f"[EC200U] {message}", flush=True)

    def find_port(self) -> str | None:
        """Return /dev/ttyAMA0 when that GPIO UART answers as an EC200U."""
        try:
            with modem_lock():
                return self._find_port()
        except TimeoutError:
            return None

    def _find_port(self) -> str | None:
        if not Path(self.port).exists():
            return None
        if self._probe_at(self.port):
            self._at_port = self.port
            return self.port
        self._at_port = None
        return None

    def ensure_ready(self) -> str:
        """Disable EC200U sleep on the GPIO UART.

        A later call within a minute does not send AT again. Skips the
        cycle when an SMS send owns the port.
        """
        try:
            with modem_lock(blocking=False):
                return self._ensure_ready()
        except TimeoutError:
            return "busy"

    def stay_awake(self) -> str:
        return self.ensure_ready()

    def _ensure_ready(self) -> str:
        if not Path(self.port).exists():
            return self._mark_missing()
        if self._phase == "ready" and time.time() - self._last_ok < 60:
            return "ready"

        restoring = self._seen_ready and self._phase == "waiting"
        quiet = self._phase == "ready"
        if not quiet:
            self._log("Searching for modem on GPIO UART...")

        if not self._probe_at(self.port):
            self._at_port = None
            if self._phase == "ready":
                return self._mark_missing()
            self._phase = "waiting"
            return "no at port"

        if not quiet:
            self._log(f"AT interface identified ({self.port}, GPIO 14/15)")
        try:
            with serial.Serial(self.port, self.baud, timeout=0.4, write_timeout=2, exclusive=True) as ser:
                ok, changed = self._apply_qsclk(ser)
        except serial.SerialException as exc:
            self._at_port = None
            self._phase = "waiting"
            self._log(f"AT interface unavailable ({exc.__class__.__name__})")
            return "unavailable"

        if not ok:
            self._phase = "waiting"
            self._log("QSCLK verification failed")
            return "qsclk failed"

        if restoring:
            self._log("Modem reconnected")
        if changed:
            self._log("Modem sleep disabled")
        if not quiet:
            self._log("QSCLK verification successful")
        if restoring:
            self._log("Configuration restored")
        if not quiet:
            self._log("Ready for communication")
        self._phase = "ready"
        self._seen_ready = True
        self._at_port = self.port
        self._last_ok = time.time()
        return "ready"

    def _mark_missing(self) -> str:
        self._at_port = None
        self._last_ok = 0.0
        if self._phase == "ready":
            self._log("UART connection lost")
            self._log("Waiting for reconnection...")
            self._phase = "waiting"
            return "waiting"
        if self._phase == "idle":
            self._log("Searching for modem on GPIO UART...")
            self._phase = "waiting"
            return "searching"
        return "waiting"

    def _probe_at(self, path: str) -> bool:
        """True when this interface answers AT and reports an EC200 model.

        A port already opened by another program (PPP, ModemManager, an SMS
        send) is left alone.
        """
        try:
            ser = serial.Serial(
                path, self.baud, timeout=0.3, write_timeout=2, exclusive=True
            )
        except serial.SerialException:
            return False
        try:
            self._wake(ser)
            reply = self._at(ser, "AT", timeout=1.2)
            if not self._ok_line(reply):
                return False
            model = self._model_name(self._at(ser, "AT+CGMM", timeout=1.5))
            return bool(model) and "EC200" in model.upper()
        except Exception:
            return False
        finally:
            try:
                ser.close()
            except Exception:
                pass

    def _apply_qsclk(self, ser: serial.Serial) -> tuple[bool, bool]:
        """Make sure sleep is off. Returns (verified, changed).

        Does nothing when AT+QSCLK? is already 0. Never sends CFUN or QPOWD.
        """
        current = self._at(ser, "AT+QSCLK?", timeout=2)
        if "+QSCLK:0" in current.replace(" ", ""):
            return True, False
        turned_off = self._at(ser, "AT+QSCLK=0", timeout=3)
        if not self._ok_line(turned_off):
            return False, False
        verify = self._at(ser, "AT+QSCLK?", timeout=2)
        if "+QSCLK:0" not in verify.replace(" ", ""):
            return False, False
        self._at(ser, "AT&W", timeout=3)
        return True, True

    def send_text(self, numbers: list[str], text: str) -> list[SmsSendResult]:
        try:
            with modem_lock():
                return self._send_text(numbers, text)
        except TimeoutError:
            return [SmsSendResult(to=n, ok=False, error="modem is busy") for n in numbers]

    def _send_text(self, numbers: list[str], text: str) -> list[SmsSendResult]:
        port = self._find_port()
        if not port:
            hint = (
                f"GPIO UART {self.port} did not answer "
                "(module TXD to Pi pin 10, module RXD to Pi pin 8)"
            )
            return [SmsSendResult(to=n, ok=False, error=hint) for n in numbers]

        results: list[SmsSendResult] = []
        try:
            with serial.Serial(port, self.baud, timeout=0.4, write_timeout=2, exclusive=True) as ser:
                self._prepare(ser)
                for number in numbers:
                    results.append(self._send_one(ser, number, text))
        except Exception as exc:
            if not results:
                return [SmsSendResult(to=n, ok=False, error=str(exc)) for n in numbers]
            results.append(SmsSendResult(to="", ok=False, error=str(exc)))
        return results

    def _prepare(self, ser: serial.Serial) -> None:
        self._wake(ser)
        self._at(ser, "AT")
        self._at(ser, "ATE0")
        self._at(ser, "AT+CMEE=2")
        pin = self._at(ser, "AT+CPIN?", timeout=3)
        if "SIM PIN" in pin and self.sim_pin:
            self._at(ser, f'AT+CPIN="{self.sim_pin}"', timeout=8)
        self._at(ser, "AT+CMGF=1")
        self._at(ser, 'AT+CSCS="GSM"')
        ok, changed = self._apply_qsclk(ser)
        if changed and ok:
            self._log("Modem sleep disabled")
        elif not ok:
            self._log("QSCLK verification failed")

    def _send_one(self, ser: serial.Serial, number: str, text: str) -> SmsSendResult:
        pin = self._at(ser, "AT+CPIN?", timeout=3)
        if "READY" not in pin:
            detail = " ".join(pin.split())
            return SmsSendResult(to=number, ok=False, error=detail or "SIM not ready")
        prompt = self._at(ser, f'AT+CMGS="{number}"', timeout=8, wait_for=">")
        if ">" not in prompt:
            detail = " ".join(prompt.split())
            return SmsSendResult(to=number, ok=False, error=detail or "no SMS prompt")
        time.sleep(0.1)
        ser.write(text.encode("ascii", errors="replace") + b"\x1a")
        ser.flush()
        reply = self._read_until(ser, timeout=45, wait_for="+CMGS:")
        if "+CMGS:" in reply:
            return SmsSendResult(to=number, ok=True)
        detail = " ".join(reply.split())
        return SmsSendResult(to=number, ok=False, error=detail or "no reply from modem")

    def _wake(self, ser: serial.Serial) -> None:
        """Leave text-entry mode if an earlier CMGS is still waiting."""
        try:
            ser.write(b"\x1b")
            ser.flush()
            time.sleep(0.15)
            ser.reset_input_buffer()
        except Exception:
            pass

    @staticmethod
    def _text_lines(text: str) -> list[str]:
        lines = []
        for line in text.replace("\r", "\n").split("\n"):
            line = line.strip()
            if not line:
                continue
            if all(32 <= ord(ch) < 127 for ch in line):
                lines.append(line)
            else:
                return []
        return lines

    def _ok_line(self, text: str) -> bool:
        lines = self._text_lines(text)
        return any(line == "OK" for line in lines)

    def _model_name(self, text: str) -> str:
        if not self._ok_line(text):
            return ""
        for line in self._text_lines(text):
            if line in ("OK", "ERROR") or line.startswith(("+", "AT")):
                continue
            if any(ch.isalpha() for ch in line):
                return line
        return ""

    def _at(self, ser: serial.Serial, command: str, timeout: float = 2, wait_for: str = "OK") -> str:
        ser.reset_input_buffer()
        ser.write((command + "\r").encode())
        ser.flush()
        return self._read_until(ser, timeout=timeout, wait_for=wait_for)

    def _read_until(self, ser: serial.Serial, timeout: float, wait_for: str) -> str:
        deadline = time.time() + timeout
        chunks: list[bytes] = []
        while time.time() < deadline:
            try:
                waiting = ser.in_waiting
                raw = ser.read(waiting or 1)
            except serial.SerialException:
                break
            if raw:
                chunks.append(raw)
                text = b"".join(chunks).decode("utf-8", errors="replace")
                if wait_for in text or "ERROR" in text:
                    return text
            else:
                time.sleep(0.05)
        return b"".join(chunks).decode("utf-8", errors="replace")
