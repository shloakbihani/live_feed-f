#!/usr/bin/env python3
"""Send one test SMS through the Quectel EC200U on USB.

Usage:
  python3 test_ec200u_sms.py
  python3 test_ec200u_sms.py --to +917032916273 --text "Test from daycare"
"""

from __future__ import annotations

import argparse
import time

import serial

from modem_sms import ModemSms

DEFAULT_TO = "+917032916273"
DEFAULT_TEXT = "Test from daycare"


def read_until(ser: serial.Serial, timeout: float, wait_for: str) -> str:
    deadline = time.time() + timeout
    chunks: list[bytes] = []
    while time.time() < deadline:
        raw = ser.read(ser.in_waiting or 1)
        if raw:
            chunks.append(raw)
            text = b"".join(chunks).decode("utf-8", errors="replace")
            if wait_for in text or "ERROR" in text:
                return text
        else:
            time.sleep(0.02)
    return b"".join(chunks).decode("utf-8", errors="replace")


def at(ser: serial.Serial, command: str, timeout: float = 3, wait_for: str = "OK") -> str:
    ser.reset_input_buffer()
    ser.write((command + "\r").encode())
    ser.flush()
    return read_until(ser, timeout, wait_for)


def show(label: str, reply: str) -> str:
    flat = " ".join(reply.split())
    print(f"  {label}: {flat or '(empty)'}")
    return flat


def registered(reply: str) -> bool:
    # +CREG: 0,1 or 0,5 (home / roaming). Same shape for CEREG.
    compact = reply.replace(" ", "")
    return any(token in compact for token in (",1", ",5")) and "ERROR" not in reply


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a test SMS from the EC200U")
    parser.add_argument("--to", default=DEFAULT_TO, help="Destination number in E.164")
    parser.add_argument("--text", default=DEFAULT_TEXT, help="Message body")
    parser.add_argument("--wait", type=float, default=30, help="Seconds to wait for network registration")
    args = parser.parse_args()

    number = args.to.strip().replace(" ", "")
    if not number.startswith("+"):
        number = f"+{number}"

    port = ModemSms().find_port()
    if not port:
        print("No EC200U AT port. Plug the module USB-C cable into the Pi and try again.")
        return 1

    print(f"EC200U AT port: {port}")
    print(f"To: {number}")
    print(f"Text: {args.text}")

    with serial.Serial(port, 115200, timeout=0.3, write_timeout=2, exclusive=True) as ser:
        ser.write(b"\x1b")
        time.sleep(0.15)
        ser.reset_input_buffer()
        show("AT", at(ser, "AT"))
        at(ser, "ATE0")
        at(ser, "AT+CMEE=2")
        show("model", at(ser, "AT+CGMM"))
        show("SIM", at(ser, "AT+CPIN?", timeout=3))
        show("signal", at(ser, "AT+CSQ"))
        show("cell", at(ser, 'AT+QENG="servingcell"', timeout=4))
        show("SMSC", at(ser, "AT+CSCA?"))

        deadline = time.time() + args.wait
        creg = cereg = ""
        while True:
            creg = show("CREG", at(ser, "AT+CREG?"))
            cereg = show("CEREG", at(ser, "AT+CEREG?"))
            if registered(creg) or registered(cereg):
                break
            if time.time() >= deadline:
                print("Network is not registered yet. Sending anyway.")
                break
            time.sleep(3)

        show("operator", at(ser, "AT+COPS?", timeout=8))
        at(ser, "AT+CMGF=1")
        at(ser, 'AT+CSCS="GSM"')
        # Packet-domain SMS only when the module is on LTE and not on the circuit network.
        if registered(cereg) and not registered(creg):
            show("SMS route", at(ser, "AT+CGSMS=2"))

        try:
            prompt = show("CMGS", at(ser, f'AT+CMGS="{number}"', timeout=8, wait_for=">"))
            if ">" not in prompt:
                print("Modem did not accept the number.")
                return 1
            time.sleep(0.1)
            ser.write(args.text.encode("ascii", errors="replace") + b"\x1a")
            ser.flush()
            reply = show("result", read_until(ser, 45, "+CMGS:"))
        except serial.SerialException as exc:
            print(f"USB link dropped while sending: {exc}")
            print("The module often reappears after a few seconds. If the phone did not get the text, run this script again.")
            return 1
        if "+CMGS:" in reply:
            print("SMS sent.")
            return 0
        print("SMS was not sent.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
