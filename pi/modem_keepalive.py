"""Keep the Quectel EC200U awake whenever this process is running.

Started from run_modem.sh, including at boot. Sleep is turned off on the
module (AT+QSCLK=0) and the radio is poked on a timer so it does not drop
off after the last SMS.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

from config import MODEM_BAUD, MODEM_PORT, MODEM_SIM_PIN, MODEM_WAKE_SEC
from modem_sms import ModemSms


def usb_stay_on() -> None:
    """Ask Linux not to suspend the Quectel USB device."""
    root = Path("/sys/bus/usb/devices")
    if not root.is_dir():
        return
    for device in root.iterdir():
        vendor = device / "idVendor"
        try:
            if not vendor.is_file() or vendor.read_text().strip() != "2c7c":
                continue
            (device / "power" / "control").write_text("on")
        except OSError:
            continue


def main() -> None:
    interval = max(10, MODEM_WAKE_SEC)
    modem = ModemSms(MODEM_PORT, MODEM_BAUD, MODEM_SIM_PIN)
    usb_stay_on()
    print(f"modem keepalive every {interval}s", flush=True)
    last_status = ""
    last_heartbeat = 0.0
    while True:
        started = time.time()
        try:
            status = modem.stay_awake()
        except Exception as exc:
            status = f"error {exc}"
        now = time.time()
        heartbeat = now - last_heartbeat >= 300
        if status != last_status or heartbeat or not status.startswith("awake"):
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"{stamp} {status}", flush=True)
            last_status = status
            if status.startswith("awake"):
                last_heartbeat = now
        time.sleep(max(1.0, interval - (time.time() - started)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
