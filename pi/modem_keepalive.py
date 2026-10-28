"""Keep the Quectel EC200U awake on the Pi GPIO UART.

Started from run_modem.sh, including at boot. AT commands use
/dev/ttyAMA0. The USB cable is power only.
"""

from __future__ import annotations

import sys
import time

from config import MODEM_BAUD, MODEM_PORT, MODEM_SIM_PIN, MODEM_WAKE_SEC
from modem_sms import ModemSms


def main() -> None:
    interval = max(5, min(MODEM_WAKE_SEC, 15))
    modem = ModemSms(MODEM_PORT, MODEM_BAUD, MODEM_SIM_PIN)
    while True:
        try:
            modem.ensure_ready()
        except Exception as exc:
            print(f"[EC200U] {exc}", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
