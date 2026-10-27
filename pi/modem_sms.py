"""SMS through a Quectel EC200U-CN on the USB Type-C port.

The module enumerates as several serial interfaces. Which /dev/ttyUSB
node is the AT port changes when it is plugged into a different USB
socket, so the modem is found by the USB ID verified on this Pi
(2c7c:0901) and then by an AT answer. UART pins are not used.
"""

from __future__ import annotations

import fcntl
import glob
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import serial

# Verified on this Raspberry Pi with lsusb / dmesg: Quectel EC200U, not assumed.
EC200U_VID = 0x2C7C
EC200U_PID = 0x0901

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
        self._phase = "idle"
        self._at_port: str | None = None
        self._signature: tuple[str, str] | None = None
        self._seen_ready = False
        self._power_logged = False
        self._announced_usb: str | None = None

    def candidates(self) -> list[str]:
        return self._ec200_ports()

    def _log(self, message: str) -> None:
        print(f"[EC200U] {message}", flush=True)

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
        if self._at_port and self._still_ec200(self._at_port):
            return self._at_port
        self._at_port = None
        for path in self._ec200_ports():
            if self._probe_at(path):
                self._at_port = path
                return path
        return None

    def ensure_ready(self) -> str:
        """Find the EC200U, keep USB power on, and disable modem sleep once.

        Later calls only check that the same device is still present. They
        do not send AT again until it disappears and comes back. Skips the
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
        ports = self._ec200_ports()
        if not ports:
            return self._mark_missing()

        usb_name = self._usb_sysfs_name(ports[0])
        if (
            self._phase == "ready"
            and self._signature == (usb_name, self._at_port or "")
            and self._at_port
            and self._still_ec200(self._at_port)
        ):
            return "ready"

        restoring = self._seen_ready and self._phase == "waiting"
        if self._announced_usb != usb_name:
            if self._phase == "idle":
                self._log("Searching for modem...")
            if restoring:
                self._log("Modem reconnected")
            self._log("Device detected")
            self._announced_usb = usb_name

        port = self._find_port()
        if not port:
            self._phase = "waiting"
            return "no at port"

        self._log(f"AT interface identified ({port})")
        self._log_usb_power(port)
        try:
            with serial.Serial(port, self.baud, timeout=0.4, write_timeout=2, exclusive=True) as ser:
                ser.dtr = True
                ser.rts = True
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

        if changed:
            self._log("Modem sleep disabled")
        self._log("QSCLK verification successful")
        if restoring:
            self._log("Configuration restored")
        self._log("Ready for communication")
        self._phase = "ready"
        self._seen_ready = True
        self._signature = (usb_name, port)
        self._at_port = port
        return "ready"

    def _mark_missing(self) -> str:
        self._at_port = None
        self._signature = None
        self._power_logged = False
        self._announced_usb = None
        if self._phase == "ready":
            self._log("USB connection lost")
            self._log("Waiting for reconnection...")
            self._phase = "waiting"
            return "waiting"
        if self._phase == "idle":
            self._log("Searching for modem...")
            self._phase = "waiting"
            return "searching"
        return "waiting"

    def _ec200_ports(self) -> list[str]:
        if self.port:
            return [self.port] if self._still_ec200(self.port) else []
        found: list[str] = []
        try:
            from serial.tools import list_ports
            listed = list_ports.comports()
        except Exception:
            listed = []
        for info in listed:
            if info.vid == EC200U_VID and info.pid == EC200U_PID and info.device:
                found.append(info.device)
        if not found:
            for pattern in ("/dev/ttyUSB*", "/dev/ttyACM*"):
                for path in glob.glob(pattern):
                    if self._usb_device(path) is not None:
                        found.append(path)
        return sorted(set(found))

    def _still_ec200(self, path: str) -> bool:
        return Path(path).exists() and self._usb_device(path) is not None

    def _usb_device(self, port: str) -> Path | None:
        """Sysfs directory of this tty's EC200U, never a parent hub or another USB device."""
        start = Path("/sys/class/tty") / Path(port).name / "device"
        if not start.exists():
            return None
        current = start.resolve()
        for _ in range(10):
            vendor_file = current / "idVendor"
            product_file = current / "idProduct"
            if vendor_file.is_file() and product_file.is_file():
                vid = vendor_file.read_text().strip().lower()
                pid = product_file.read_text().strip().lower()
                if vid == f"{EC200U_VID:04x}" and pid == f"{EC200U_PID:04x}":
                    return current
                return None
            parent = current.parent
            if parent == current:
                return None
            current = parent
        return None

    def _usb_sysfs_name(self, port: str) -> str:
        device = self._usb_device(port)
        return device.name if device is not None else ""

    def _disable_autosuspend(self, port: str) -> str:
        device = self._usb_device(port)
        if device is None:
            return "missing"
        power = device / "power"
        control = power / "control"
        delay = power / "autosuspend"
        try:
            held = control.read_text().strip() == "on"
        except OSError:
            return "denied"
        if not held:
            try:
                control.write_text("on")
                held = control.read_text().strip() == "on"
            except OSError:
                return "denied"
        # -1 disables the idle timer if power/control is later set back to auto.
        # That file is root-only; control=on already forbids autosuspend.
        if delay.is_file():
            try:
                if delay.read_text().strip() != "-1":
                    delay.write_text("-1")
            except OSError:
                pass
        return "on" if held else "failed"

    def _log_usb_power(self, port: str) -> None:
        if self._power_logged:
            return
        result = self._disable_autosuspend(port)
        if result == "on":
            self._log("USB power held on (autosuspend off)")
            self._power_logged = True
        elif result == "denied":
            self._log("USB autosuspend not changed (permission denied)")
            self._power_logged = True
        elif result == "failed":
            self._log("USB autosuspend setting did not stay on")
            self._power_logged = True

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
            hint = "no USB modem port (plug in the EC200U Type-C cable)"
            if self.port:
                hint = f"modem port {self.port} did not answer AT"
            return [SmsSendResult(to=n, ok=False, error=hint) for n in numbers]

        results: list[SmsSendResult] = []
        try:
            self._log_usb_power(port)
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
