"""
Application configuration — loaded from .env for deployment.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

_ENV_FILE = Path(__file__).parent / ".env"
if not _ENV_FILE.exists():
    raise FileNotFoundError(
        f"Missing {_ENV_FILE}. Copy pi/.env.example to pi/.env and fill in values."
    )
load_dotenv(_ENV_FILE, override=True)

# Camera
CAMERA_IP = os.getenv("CAMERA_IP", "122.175.45.21")
CAMERA_USER = os.getenv("CAMERA_USER", "admin")
CAMERA_PASS = os.getenv("CAMERA_PASS", "")
RTSP_PORT = int(os.getenv("RTSP_PORT", "554"))
CAMERA_CHANNEL = int(os.getenv("CAMERA_CHANNEL", "1"))
CAMERA_SUBTYPE = int(os.getenv("CAMERA_SUBTYPE", "1"))

HTTP_PORT = 80
HTTPS_PORT = 443
DAHUA_TCP_PORT = 37777

# RTSPS URLs (rtsps:// required for this camera)
RTSP_URLS = [
    f"rtsps://{CAMERA_USER}:{CAMERA_PASS}@{CAMERA_IP}:{RTSP_PORT}/video/live?channel={CAMERA_CHANNEL}&subtype={CAMERA_SUBTYPE}",
    f"rtsps://{CAMERA_USER}:{CAMERA_PASS}@{CAMERA_IP}:{RTSP_PORT}/video/live?channel={CAMERA_CHANNEL}&subtype={1 - CAMERA_SUBTYPE}",
    f"rtsps://{CAMERA_USER}:{CAMERA_PASS}@{CAMERA_IP}:{RTSP_PORT}/cam/realmonitor?channel={CAMERA_CHANNEL}&subtype=0",
    f"rtsps://{CAMERA_USER}:{CAMERA_PASS}@{CAMERA_IP}:{RTSP_PORT}/",
]

WS_ENDPOINTS = [
    f"ws://{CAMERA_IP}/websocket",
    f"ws://{CAMERA_IP}/live",
    f"ws://{CAMERA_IP}:80/websocket",
    f"ws://{CAMERA_IP}/RPC2_WebSocket",
    f"ws://{CAMERA_IP}/videostream",
]

HTTP_SNAPSHOT = f"http://{CAMERA_IP}/cgi-bin/snapshot.cgi?channel=1"
HTTP_LOGIN = f"http://{CAMERA_IP}/RPC2_Login"
HTTP_STREAM = f"http://{CAMERA_IP}/cgi-bin/mjpg/video.cgi?channel=1&subtype=1"

# Violence model.
# best.pt is the original classifier and is not loaded.
# best_daycare_ft.pt is the calm-room fine-tune.
# best_action_ft.pt learned the earlier struggle clips.
# best_newdata_ft.pt is the latest fine-tune, trained from best_action_ft.pt.
_WEIGHTS_DIR = Path(__file__).parent / "violence_yolov8n_cls-4" / "weights"
_weights_raw = os.getenv(
    "VIOLENCE_WEIGHTS",
    str(_WEIGHTS_DIR / "best_newdata_ft.pt"),
)
_weights_path = Path(_weights_raw)
if not _weights_path.is_absolute():
    _weights_path = Path(__file__).parent / _weights_path
VIOLENCE_WEIGHTS = str(_weights_path)
VIOLENCE_CONF = float(os.getenv("VIOLENCE_CONF", "0.60"))
VIOLENCE_EVERY_N = int(os.getenv("VIOLENCE_EVERY_N", "4"))
# Alert after CONFIRM_HITS violence frames inside CONFIRM_SPAN_SEC.
# Calm frames in between do not reset the count; old hits age out.
CONFIRM_HITS = int(os.getenv("CONFIRM_HITS", "8"))
CONFIRM_SPAN_SEC = float(os.getenv("CONFIRM_SPAN_SEC", "45"))
CONFIRM_WINDOW = int(os.getenv("CONFIRM_WINDOW", "10"))
ALERT_COOLDOWN_SEC = float(os.getenv("ALERT_COOLDOWN_SEC", "300"))
# After a confirmed alert, skip YOLO for this many seconds (keeps Pi cool, cuts lag).
INFER_PAUSE_AFTER_ALERT_SEC = float(os.getenv("INFER_PAUSE_AFTER_ALERT_SEC", "900"))
# Decode smaller/slower frames in ffmpeg so Python is not flooded with 720p@25.
DECODE_WIDTH = int(os.getenv("DECODE_WIDTH", "416"))
DECODE_FPS = float(os.getenv("DECODE_FPS", "5"))
SAVE_CLIPS = os.getenv("SAVE_CLIPS", "false").lower() in ("1", "true", "yes")
TORCH_NUM_THREADS = int(os.getenv("TORCH_NUM_THREADS", "2"))

# Deployment
DEPLOY_HEADLESS = os.getenv("DEPLOY_HEADLESS", "true").lower() in ("1", "true", "yes")

# SMS via Quectel EC200U MAIN UART on the Pi GPIO header.
# Type-C is power only. AT commands use /dev/ttyAMA0 (pin 8 TXD, pin 10 RXD).
SMS_ENABLED = os.getenv("SMS_ENABLED", "false").lower() in ("1", "true", "yes")
SMS_TO = os.getenv("SMS_TO", "")
MODEM_PORT = os.getenv("MODEM_PORT", "/dev/ttyAMA0").strip() or "/dev/ttyAMA0"
MODEM_BAUD = int(os.getenv("MODEM_BAUD", "115200"))
MODEM_SIM_PIN = os.getenv("MODEM_SIM_PIN", "").strip()
MODEM_WAKE_SEC = int(os.getenv("MODEM_WAKE_SEC", "30"))

# Email (optional SMTP alert, e.g. personal Gmail with an App Password).
# fallback: send only when the GPIO UART SMS did not go out
# (or, if SMS is off, when the dashboard push reached nobody).
# always: send on every alert, even if SMS and push succeeded.
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() in ("1", "true", "yes")
EMAIL_MODE = os.getenv("EMAIL_MODE", "fallback").strip().lower()
if EMAIL_MODE not in ("fallback", "always"):
    EMAIL_MODE = "fallback"
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").replace(" ", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "") or SMTP_USER
EMAIL_TO = os.getenv("EMAIL_TO", "")
EMAIL_SUBJECT = os.getenv("EMAIL_SUBJECT", "Alert: Safety incident at Daycare")
EMAIL_BODY = os.getenv(
    "EMAIL_BODY",
    "Alert: Unusual / Safety incident reported at Daycare, Please check.",
)

# Supabase: alert rows, plus snapshot files in Storage
SUPABASE_LOGGING = os.getenv("SUPABASE_LOGGING", "false").lower() in ("1", "true", "yes")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "detections")

# Daycare identity (one Pi per site)
DAYCARE_NAME = os.getenv("DAYCARE_NAME", "")
DAYCARE_TZ = os.getenv("DAYCARE_TZ", "Asia/Kolkata")

# Web portal ingest (Pi posts detections after the Supabase Storage upload)
PORTAL_URL = os.getenv("PORTAL_URL", "").rstrip("/")
PORTAL_INGEST_KEY = os.getenv("PORTAL_INGEST_KEY", "")


def parse_sms_recipients(raw: str | None = None) -> list[str]:
    """Parse comma/semicolon/newline-separated phone numbers into E.164 list."""
    text = raw if raw is not None else SMS_TO
    numbers: list[str] = []
    for part in text.replace(";", ",").replace("\n", ",").split(","):
        number = part.strip().replace(" ", "")
        if not number:
            continue
        if not number.startswith("+"):
            number = f"+{number}"
        numbers.append(number)
    return numbers


def parse_email_recipients(raw: str | None = None) -> list[str]:
    """Parse comma/semicolon/newline-separated email addresses."""
    text = raw if raw is not None else EMAIL_TO
    return [p.strip() for p in text.replace(";", ",").replace("\n", ",").split(",") if p.strip()]

