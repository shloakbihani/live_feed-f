"""SMS through a Quectel EC200U-CN on the USB Type-C port.

The module enumerates as several /dev/ttyUSB* ports. Only one of them
accepts AT commands (on this board, the last port). The others are
diagnostic, GPS, and modem data and will not send an SMS. UART pins
are not used.
"""

from __future__ import annotations

import fcntl
import glob
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import serial

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

    The keepalive and an SMS send share the same USB port. A second
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
        self.port = (port or "").strip()
        self.baud = baud
        self.sim_pin = (sim_pin or "").strip()

    def candidates(self) -> list[str]:
        if self.port:
            return [self.port]
        found = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
        return sorted(found)

    def find_port(self) -> str | None:
        """Return the USB port that answers AT and reports a modem model.

        The first ttyUSB device often replies to a bare AT, or has the
        letters "OK" inside diagnostic traffic, and then rejects CMGS.
        A port is used only when AT+CGMM returns a readable model name.
        """
        try:
            with modem_lock():
                return self._find_port()
        except TimeoutError:
            return None

    def _find_port(self) -> str | None:
        for path in self.candidates():
            try:
                with serial.Serial(path, self.baud, timeout=0.3, write_timeout=2) as ser:
                    self._wake(ser)
                    reply = self._at(ser, "AT", timeout=1.2)
                    if not self._ok_line(reply):
                        continue
                    model = self._at(ser, "AT+CGMM", timeout=1.5)
            except Exception:
                continue
            if self._model_name(model):
                return path
        return None

    def stay_awake(self) -> str:
        """Disable EC200U sleep and poke the radio so it stays registered.

        Safe to call often. Skips the cycle when an SMS send owns the port.
        """
        try:
            with modem_lock(blocking=False):
                return self._stay_awake()
        except TimeoutError:
            return "busy"

    def _stay_awake(self) -> str:
        port = self._find_port()
        if not port:
            return "no modem"
        with serial.Serial(port, self.baud, timeout=0.4, write_timeout=2) as ser:
            ser.dtr = True
            ser.rts = True
            self._wake(ser)
            self._at(ser, "AT")
            self._at(ser, "ATE0")
            sleep = self._at(ser, "AT+QSCLK?", timeout=2)
            if "+QSCLK:0" not in sleep.replace(" ", ""):
                turned_off = self._at(ser, "AT+QSCLK=0", timeout=3)
                if not self._ok_line(turned_off):
                    detail = " ".join(turned_off.split()) or "no reply"
                    return f"{port} could not disable sleep ({detail})"
                self._at(ser, "AT&W", timeout=3)
            radio = self._at(ser, "AT+CFUN?", timeout=3)
            if "+CFUN:1" not in radio.replace(" ", ""):
                self._at(ser, "AT+CFUN=1", timeout=15)
            signal = self._at(ser, "AT+CSQ", timeout=3)
        level = ""
        for part in signal.replace("\r", "\n").split("\n"):
            if "+CSQ:" in part:
                level = part.strip()
                break
        return f"awake {port} {level}".strip()

    def send_text(self, numbers: list[str], text: str) -> list[SmsSendResult]:
        try:
            with modem_lock():
                return self._send_text(numbers, text)
        except TimeoutError:
            return [SmsSendResult(to=n, ok=False, error="modem is busy") for n in numbers]

    def _send_text(self, numbers: list[str], text: str) -> list[SmsSendResult]:
        port = self._find_port()
        if not port:
            hint = "no USB modem port (plug in the EC200U Type-C cable)"
            if self.port:
                hint = f"modem port {self.port} did not answer AT"
            return [SmsSendResult(to=n, ok=False, error=hint) for n in numbers]

        results: list[SmsSendResult] = []
        try:
            with serial.Serial(port, self.baud, timeout=0.4, write_timeout=2) as ser:
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

    def _send_one(self, ser: serial.Serial, number: str, text: str) -> SmsSendResult:
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
