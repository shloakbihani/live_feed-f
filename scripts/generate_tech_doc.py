#!/usr/bin/env python3
"""Generate the project technical documentation Word file."""

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "Technical_Documentation.docx"
NAVY = RGBColor(0x1A, 0x37, 0x5E)
MUTED = RGBColor(0x55, 0x55, 0x55)


def h(doc, text, level=1):
    heading = doc.add_heading(text, level=level)
    for run in heading.runs:
        run.font.color.rgb = NAVY


def bullet(doc, text, bold=""):
    p = doc.add_paragraph(style="List Bullet")
    if bold:
        p.add_run(bold).bold = True
        p.add_run(text)
    else:
        p.add_run(text)


def code(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = "Consolas"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
    run.font.size = Pt(9.5)


def table(doc, headers, rows):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    for i, title in enumerate(headers):
        t.rows[0].cells[i].text = title
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = val


def build() -> Document:
    doc = Document()

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("Daycare Violence Detection System\n")
    r.bold = True
    r.font.size = Pt(22)
    r.font.color.rgb = NAVY
    s = title.add_run("Technical Documentation")
    s.font.size = Pt(16)
    s.font.color.rgb = MUTED

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(f"Version: current repository state\n").italic = True
    meta.add_run(f"Date: {date.today().strftime('%d %B %Y')}\n").italic = True
    meta.add_run("Audience: engineers, scholars, and deployment staff").italic = True

    h(doc, "1. Purpose")
    doc.add_paragraph(
        "This system watches a CP Plus / Dahua CCTV live stream at a daycare, "
        "classifies each sampled frame as violence or non-violence, and notifies staff. "
        "The machine-learning model runs on a Raspberry Pi (or laptop) on the same local "
        "network as the camera. Snapshots are stored in Supabase Storage. A shared web "
        "dashboard lets each daycare review, save, or delete its own events. Optional SMS "
        "alerts are sent through Twilio from the Pi."
    )
    doc.add_paragraph(
        "The product is designed for several sites (typically 3–6 daycares). Each site has "
        "its own Pi and camera. There is one dashboard URL for all sites."
    )

    h(doc, "2. Design principles")
    bullet(doc, "The camera stays on the LAN. The cloud never pulls RTSP.", "Edge inference: ")
    bullet(doc, "pi/ only watches video and publishes events. web/ only shows and deletes them.", "Split services: ")
    bullet(doc, "Staff log in with camera IP + camera password and see only their site.", "Tenant isolation: ")
    bullet(doc, "Unsaved detections expire at local midnight unless staff click Save.", "Retention: ")
    bullet(doc, "After an alert, YOLO pauses so the Pi stays cool and does not spam SMS.", "Thermal / alert throttle: ")

    h(doc, "3. System architecture")
    code(
        doc,
        "Camera (RTSPS :554)\n"
        "        │  LAN only\n"
        "        ▼\n"
        "Raspberry Pi  —  ffmpeg decode  —  YOLOv8-cls (224×224)\n"
        "        │\n"
        "        ├── JPEG ──► Supabase Storage  (bucket: detections / {camera-ip}/ )\n"
        "        ├── row  ──► Supabase table   (violence_alerts, optional log)\n"
        "        ├── JSON ──► Web POST /api/detections  (Render or VPS)\n"
        "        └── SMS  ──► Twilio  (optional, per-Pi SMS_TO)\n"
        "                          │\n"
        "                          ▼\n"
        "                 Web dashboard (Flask)\n"
        "                 Login · Save · Delete · midnight purge",
    )
    doc.add_paragraph(
        "The dashboard never opens the camera. It only stores metadata and public snapshot URLs. "
        "Delete on the website removes the SQLite row and the file in Supabase Storage."
    )

    h(doc, "4. Repository layout")
    table(
        doc,
        ["Path", "Role"],
        [
            ["pi/", "Edge service: stream, model, upload, SMS, portal ingest"],
            ["web/", "Flask dashboard, SQLite tenants, Save/Delete, purge"],
            ["violence_yolov8n_cls-4/weights/best.pt", "Trained classification weights"],
            ["supabase/schema.sql", "violence_alerts table + detections bucket"],
            ["render.yaml", "Render Blueprint for the dashboard only"],
            ["WEB_DEPLOY.md", "How to host the dashboard for many Pis"],
            ["docs/", "Generated Word guides (this file, Twilio, client report)"],
            ["pi/.env / web/.env", "Secrets; not committed"],
        ],
    )

    h(doc, "5. Pi service (edge)")
    h(doc, "5.1 Entry point", level=2)
    doc.add_paragraph(
        "Production command: python3 violence_monitor.py --headless (from the pi/ directory). "
        "Config is loaded only from pi/.env."
    )
    h(doc, "5.2 Live stream", level=2)
    doc.add_paragraph(
        "Cameras use RTSPS (TLS) on port 554. The working URL pattern is:"
    )
    code(
        doc,
        "rtsps://USER:PASS@CAMERA_IP:554/video/live?channel=1&subtype=1",
    )
    doc.add_paragraph(
        "subtype=1 is the sub-stream (typically 1280×720 HEVC) and is required on Raspberry Pi. "
        "Main stream 2560×1440 HEVC is too heavy for reliable decode. "
        "OpenCV’s bundled FFmpeg on some platforms cannot decode this stream, so frames are "
        "read from an ffmpeg subprocess as raw BGR."
    )
    doc.add_paragraph("Pi-friendly decode defaults (overridable in pi/.env):")
    table(
        doc,
        ["Variable", "Default", "Meaning"],
        [
            ["DECODE_WIDTH", "416", "Max frame width after ffmpeg scale"],
            ["DECODE_FPS", "5", "Frames delivered to Python per second"],
            ["VIOLENCE_EVERY_N", "4", "Run YOLO every N decoded frames (~1.25 infer/s)"],
            ["CONFIRM_HITS", "8", "Violence inferences required in the window"],
            ["CONFIRM_WINDOW", "10", "Recent inferences to count (8 of 10 ≈ 8 s)"],
            ["TORCH_NUM_THREADS", "2", "Leave CPU for ffmpeg"],
            ["SAVE_CLIPS", "false", "Do not encode MP4 on the Pi"],
        ],
    )
    doc.add_paragraph(
        "Debian/Raspberry Pi ffmpeg rejects -tls_verify. The code never passes that flag to ffmpeg; "
        "ffprobe may still use it if the binary accepts it."
    )

    h(doc, "5.3 Model", level=2)
    doc.add_paragraph(
        "Ultralytics YOLOv8 nano classifier (yolov8n-cls), trained 25 epochs, image size 224, "
        "two classes: non_violence (0) and violence (1). Weights: "
        "violence_yolov8n_cls-4/weights/best.pt. Reported validation accuracy was about 95% "
        "(approximate FP 5.7%, FN 4.2% on the training split — treat as lab numbers, not a field SLA)."
    )
    doc.add_paragraph(
        "Inference always resizes to 224×224 before predict(). A frame is violence only if "
        "violence is the top-1 class and its score is at or above VIOLENCE_CONF (default 0.60)."
    )
    h(doc, "5.4 Confirmation (when a frame becomes an alert)", level=2)
    doc.add_paragraph(
        "A single inference above VIOLENCE_CONF is not enough. The monitor uses M-of-N: "
        "CONFIRM_HITS of the last CONFIRM_WINDOW inferences must be violence (defaults 8 of 10). "
        "These are model reads, not raw camera frames. At the default decode rate that is about "
        "an 8-second window (10 inferences × every 4th frame ÷ 5 fps). One or two non-violence "
        "flickers in that window do not cancel the others."
    )
    doc.add_paragraph(
        "If CONFIRM_WINDOW equals CONFIRM_HITS, this is the same as requiring a consecutive streak. "
        "After a fired alert, the window is cleared and YOLO pauses (INFER_PAUSE_AFTER_ALERT_SEC)."
    )
    doc.add_paragraph(
        "Do not set CONFIRM_WINDOW to 15 if you mean 15 camera frames. Fifteen inferences at the "
        "default throttle would be about 12 seconds. Override in pi/.env or with --confirm / "
        "--confirm-window."
    )

    h(doc, "5.5 Snapshot written to Supabase", level=2)
    doc.add_paragraph(
        "The image stored locally and in Supabase Storage is the highest-confidence violence "
        "frame from the current confirmation window — not the last frame in the streak. "
        "Example: scores 72%, 81%, 68%, 74% → the uploaded JPEG and the logged confidence "
        "are both from the 81% frame. The same JPEG is written under pi/alerts/ "
        "(quality 70) and uploaded as {ip-slug}/alert_YYYYMMDD_HHMMSS.jpg."
    )
    doc.add_paragraph(
        "If SAVE_CLIPS is true, a short MP4 of the recent decoded buffer is also written locally. "
        "That clip is still a time window of recent frames; only the still image is chosen by "
        "highest confidence."
    )

    h(doc, "5.6 After an alert", level=2)
    bullet(doc, "Highest-confidence JPEG (quality 70) written under pi/alerts/.", "Local: ")
    bullet(doc, "Same JPEG uploaded to Supabase Storage path {ip-slug}/alert_YYYYMMDD_HHMMSS.jpg.", "Storage: ")
    bullet(doc, "JSON POST to PORTAL_URL/api/detections with header X-Ingest-Key.", "Dashboard: ")
    bullet(doc, "Twilio SMS to every number in SMS_TO if SMS_ENABLED=true.", "SMS: ")
    bullet(doc, "Optional insert into Supabase violence_alerts.", "Log: ")
    doc.add_paragraph(
        "Upload, portal POST, and SMS run on a background thread so the video loop does not block."
    )
    table(
        doc,
        ["Timer", "Default in code", "Effect"],
        [
            ["INFER_PAUSE_AFTER_ALERT_SEC", "900 (15 min)", "YOLO is skipped; stream still drains"],
            ["ALERT_COOLDOWN_SEC", "300 (5 min)", "No second snapshot/SMS even if YOLO is running"],
        ],
    )
    doc.add_paragraph(
        "pi/.env overrides these. If both are 300, the running system pauses and cools down for 5 minutes."
    )

    h(doc, "6. Web service (dashboard)")
    doc.add_paragraph(
        "Flask app in web/. Local: python3 app.py (port 8080). Production: gunicorn via web/Dockerfile "
        "on Render (service daycare-dashboard) or a VPS."
    )
    h(doc, "6.1 Authentication", level=2)
    doc.add_paragraph(
        "Username = camera IP. Password = camera password, stored as a Werkzeug hash in SQLite. "
        "Register tenants with web/seed.py or WEB_TENANTS=ip|password|Name;ip|password|Name."
    )
    h(doc, "6.2 Persistence", level=2)
    doc.add_paragraph(
        "SQLite file: DATA_DIR/portal.db (local web/data/, Render /var/data with a disk). "
        "Tables: tenants (camera_ip, password_hash, daycare_name); detections (metadata, snapshot_url, "
        "storage path in cloudinary_public_id, saved flag, expires_at)."
    )
    h(doc, "6.3 Retention", level=2)
    doc.add_paragraph(
        "Unsaved rows expire at the next local midnight (DAYCARE_TZ, default Asia/Kolkata). "
        "Purge runs on dashboard load and ingest. Save keeps the row. Delete removes the row and "
        "the Storage object. Older Cloudinary IDs (no image extension) can still be deleted if Cloudinary keys remain on the web service."
    )
    h(doc, "6.4 HTTP API", level=2)
    table(
        doc,
        ["Method / path", "Auth", "Purpose"],
        [
            ["GET /health", "none", "Render health check"],
            ["GET /login, POST /login", "form", "Staff login"],
            ["GET /dashboard", "session", "Today + saved archive"],
            ["POST /detections/<id>/save", "session", "Keep after midnight"],
            ["POST /detections/<id>/unsave", "session", "Return to daily expiry"],
            ["POST /detections/<id>/delete", "session", "Remove row + file"],
            ["POST /api/detections", "X-Ingest-Key", "Pi ingest"],
            ["GET /api/purge", "X-Ingest-Key", "Manual expiry sweep"],
            ["GET /api/board", "session", "Lightweight counts for UI"],
        ],
    )
    doc.add_paragraph("Ingest JSON body:")
    code(
        doc,
        "{\n"
        '  "camera_ip": "192.168.1.50",\n'
        '  "daycare_name": "Sunshine Delhi",\n'
        '  "detected_at": "2026-09-26T11:16:55+05:30",\n'
        '  "confidence": 0.85,\n'
        '  "label": "violence",\n'
        '  "channel": 1,\n'
        '  "snapshot_url": "https://…/detections/…/alert_….jpg",\n'
        '  "cloudinary_public_id": "192-168-1-50/alert_….jpg"\n'
        "}",
    )
    doc.add_paragraph(
        "Unknown camera_ip is rejected (404) until the daycare is seeded. "
        "Wrong ingest key is 401."
    )

    h(doc, "7. Data stores")
    h(doc, "7.1 Supabase Storage", level=2)
    doc.add_paragraph(
        "Bucket detections (public read). Object key: {camera-ip-with-dashes}/alert_{timestamp}.jpg. "
        "The Pi creates the bucket if missing when using a service-role key. "
        "The dashboard delete path removes that object."
    )
    h(doc, "7.2 Supabase table violence_alerts", level=2)
    doc.add_paragraph(
        "Optional audit log from the Pi (SUPABASE_LOGGING=true). Columns include detected_at, "
        "camera_ip, confidence, label, snapshot_url, and SMS status fields (historically named whatsapp_*)."
    )
    h(doc, "7.3 SQLite on the web host", level=2)
    doc.add_paragraph(
        "Source of truth for the portal UI. Without a Render disk, this file is lost on deploy."
    )

    h(doc, "8. SMS (Twilio)")
    doc.add_paragraph(
        "Implemented only in pi/notifier.py. After publish, AlertNotifier.send_sms() calls "
        "Twilio messages.create(). Modes:"
    )
    bullet(doc, "TWILIO_SMS_MODE=template — body is the template name (India trial: sms_internal_alerts).", "template: ")
    bullet(doc, "TWILIO_SMS_MODE=content — ContentSid HX… with {{1}} = date/time.", "content: ")
    bullet(doc, "free-form body from AlertEvent.message_text() when templates are off.", "auto: ")
    doc.add_paragraph(
        "See docs/Twilio_SMS_Setup_Guide.docx for a scholar walkthrough. "
        "Error 20003 is an account/geo/trial policy failure, not a camera failure."
    )

    h(doc, "9. Multi-site deployment")
    doc.add_paragraph("One dashboard, N Pis. Example for three daycares:")
    table(
        doc,
        ["Site", "On the Pi", "On the web"],
        [
            ["Delhi", "CAMERA_IP / pass / DAYCARE_NAME unique; PORTAL_URL = public HTTPS", "seed that IP + password"],
            ["Noida", "Different CAMERA_*; same PORTAL_INGEST_KEY and Supabase keys", "second seed row"],
            ["Gurgaon", "Same pattern", "third seed row"],
        ],
    )
    doc.add_paragraph(
        "PORTAL_URL must be the public Render/VPS URL (for example https://daycare-dashboard-qnvl.onrender.com). "
        "http://127.0.0.1:8080 only works when the monitor and Flask run on the same machine."
    )
    doc.add_paragraph(
        "Staff at each site log in with that site’s camera IP. They never see another site’s detections."
    )

    h(doc, "10. Deployment")
    h(doc, "10.1 Pi", level=2)
    code(
        doc,
        "cd pi\n"
        "pip3 install -r requirements.txt\n"
        "sudo apt install ffmpeg   # Raspberry Pi / Debian\n"
        "cp .env.example .env      # then edit\n"
        "python3 violence_monitor.py --headless",
    )
    doc.add_paragraph("Optional systemd unit: deploy/violence-monitor.service (WorkingDirectory = …/pi).")
    h(doc, "10.2 Web (Render)", level=2)
    doc.add_paragraph(
        "Blueprint render.yaml builds web/Dockerfile, health check GET /health, region Singapore, "
        "Starter plan, disk /var/data. Set PORTAL_INGEST_KEY, PORTAL_SECRET_KEY, SUPABASE_*, WEB_TENANTS. "
        "Details: WEB_DEPLOY.md."
    )
    h(doc, "10.3 Web (VPS)", level=2)
    doc.add_paragraph("gunicorn --bind 0.0.0.0:8080 --workers 1 (SQLite is not safe with many workers). "
                      "Unit file: deploy/daycare-dashboard.service. Put Nginx + TLS in front.")

    h(doc, "11. Configuration reference")
    h(doc, "11.1 pi/.env (not web)", level=2)
    table(
        doc,
        ["Group", "Keys"],
        [
            ["Camera", "CAMERA_IP, CAMERA_USER, CAMERA_PASS, RTSP_PORT, CAMERA_CHANNEL, CAMERA_SUBTYPE"],
            ["Site", "DAYCARE_NAME"],
            ["Model", "VIOLENCE_CONF, VIOLENCE_EVERY_N, CONFIRM_HITS, CONFIRM_WINDOW, DECODE_WIDTH, DECODE_FPS, TORCH_NUM_THREADS"],
            ["Throttle", "ALERT_COOLDOWN_SEC, INFER_PAUSE_AFTER_ALERT_SEC"],
            ["Supabase", "SUPABASE_URL, keys, SUPABASE_LOGGING, SUPABASE_STORAGE_BUCKET"],
            ["Portal", "PORTAL_URL, PORTAL_INGEST_KEY"],
            ["SMS", "SMS_ENABLED, TWILIO_*, SMS_TO"],
        ],
    )
    h(doc, "11.2 web/.env or Render env", level=2)
    table(
        doc,
        ["Key", "Purpose"],
        [
            ["PORTAL_INGEST_KEY", "Must match every Pi"],
            ["PORTAL_SECRET_KEY", "Flask session secret"],
            ["SUPABASE_URL / SERVICE_ROLE_KEY", "Delete files in Storage"],
            ["SUPABASE_STORAGE_BUCKET", "Default detections"],
            ["WEB_TENANTS", "ip|password|Name;… first-boot seed"],
            ["DATA_DIR", "SQLite directory"],
            ["DAYCARE_TZ", "Midnight expiry, default Asia/Kolkata"],
            ["PORT / PORTAL_PORT", "Listen port (Render injects PORT)"],
        ],
    )

    h(doc, "12. Supporting scripts")
    table(
        doc,
        ["Script", "Use"],
        [
            ["pi/rtsp_viewer.py", "Watch the camera without ML"],
            ["pi/probe.py", "Port / HTTP probe of the camera"],
            ["web/seed.py", "Register a daycare tenant"],
            ["pi/violence_monitor.py --test-sms", "Twilio test, then exit"],
            ["pi/violence_monitor.py --probe-only", "Connect + one decoded frame"],
            ["pi/violence_monitor.py --confirm N --confirm-window M", "Override M-of-N for this run"],
        ],
    )

    h(doc, "13. Operations and known issues")
    table(
        doc,
        ["Symptom", "Cause / action"],
        [
            ["Stream interrupted, 0 bytes", "Wrong resolve / tls_verify on Debian ffmpeg; use sub-stream"],
            ["SSL CERTIFICATE_VERIFY_FAILED to Render", "macOS Python missing CA bundle; run Install Certificates.command"],
            ["unknown camera_ip", "Seed that IP on the web host"],
            ["Connection refused :8080", "Dashboard not running, or Pi still points at localhost"],
            ["Twilio 20003", "Enable India geo permissions; verify trial numbers"],
            ["Login empty after Render deploy", "Attach persistent disk at /var/data"],
            ["Main 4MP stream on Pi", "Use CAMERA_SUBTYPE=1"],
        ],
    )

    h(doc, "14. Security notes")
    bullet(doc, "Camera password is the portal password. Treat it as a staff secret; hash is stored, plaintext is not.")
    bullet(doc, "PORTAL_INGEST_KEY is a shared secret. Anyone with it can POST events for a seeded IP.")
    bullet(doc, "Supabase Storage bucket is public-read so the dashboard can show images without signed URLs. Object paths are unguessable enough for this scale, but not a substitute for private buckets if policy requires it.")
    bullet(doc, "Do not commit .env files. Service-role keys bypass Row Level Security.")
    bullet(doc, "Do not expose camera port 554 to the internet if the Pi is on-site.")

    h(doc, "15. Out of scope / future work")
    bullet(doc, "Live video on the website (intentionally omitted).")
    bullet(doc, "One Pi process watching many cameras (one CAMERA_IP per process today).")
    bullet(doc, "Signed Storage URLs and per-object ACLs.")
    bullet(doc, "Central admin console across all daycares.")
    bullet(doc, "Hardening SQLite with Postgres if the dashboard grows.")

    h(doc, "16. Related documents in this repo")
    table(
        doc,
        ["File", "Audience"],
        [
            ["docs/Technical_Documentation.docx", "This document"],
            ["docs/Twilio_SMS_Setup_Guide.docx", "Scholar — Twilio credentials and templates"],
            ["docs/Client_Deployment_Status_Report.docx", "Client — tunnel vs on-site (historical)"],
            ["WEB_DEPLOY.md", "Render / VPS dashboard deploy"],
            ["RENDER.md", "Short Render pointer"],
        ],
    )

    end = doc.add_paragraph()
    end.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = end.add_run("\n— End of technical documentation —")
    run.italic = True
    run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
    return doc


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    build().save(OUTPUT)
    print(f"Created: {OUTPUT}")


if __name__ == "__main__":
    main()
