"""Watch the Quectel EC200U and restore its awake settings after a replug.

Started from run_modem.sh, including at boot. The serial work lives in
modem_sms.py. This loop only notices arrival and departure; it does not
send AT commands on its own while the modem is already configured.
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
