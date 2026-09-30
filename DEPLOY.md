# Deployment Guide

Run the violence monitor 24/7 on a server. When violence is detected, SMS is sent to all numbers in `SMS_TO` via Twilio.

## 1. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Required | Example |
|----------|----------|---------|
| `CAMERA_IP` | Yes | `122.175.45.21` |
| `CAMERA_USER` | Yes | `admin` |
| `CAMERA_PASS` | Yes | your password |
| `SMS_TO` | Yes | `+919354501373,+919876543210` |
| `TWILIO_ACCOUNT_SID` | Yes | `ACxxxx...` |
| `TWILIO_AUTH_TOKEN` | Yes | your token |
| `TWILIO_SMS_FROM` | Yes | `+17372508034` |
| `TWILIO_SMS_TEMPLATE` | India trial | `sms_internal_alerts` |
| `DEPLOY_HEADLESS` | Yes | `true` |

**Multiple SMS numbers:** comma-separated in `SMS_TO`.

## 2. Install & test locally

```bash
pip3 install -r requirements.txt

# Test SMS only (no camera)
python3 violence_monitor.py --test-sms

# Run live monitor (headless if DEPLOY_HEADLESS=true)
python3 violence_monitor.py
```

## 3. Deploy with Docker (local / VPS)

```bash
docker compose up -d --build
docker compose logs -f
```

## 4. Deploy on Render (cloud, headless)

No live feed — worker runs ML + SMS only. See **[RENDER.md](RENDER.md)**.

1. Push repo to GitHub (include `pi/violence_yolov8n_cls-4/weights/best.pt`)
2. Render → New → Blueprint (or Background Worker + Docker)
3. Set `CAMERA_*`, `SMS_TO`, `TWILIO_*` in Environment
4. Region: **Singapore**, Plan: **Starter**

## 5. Deploy on a VPS (systemd)

```bash
sudo cp deploy/violence-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable violence-monitor
sudo systemctl start violence-monitor
sudo journalctl -u violence-monitor -f
```

Edit the service file paths if your install directory differs.

## 6. What happens on detection

1. YOLOv8 classifies frames from the camera RTSPS stream
2. After 2 consecutive violence hits (above threshold), an alert fires
3. Snapshot + clip saved to `alerts/`
4. SMS sent to **every number** in `SMS_TO`
5. Optional: row logged to Supabase if `SUPABASE_LOGGING=true`

## 7. India Twilio Trial notes

- Set `TWILIO_SMS_USE_TEMPLATE=true` and `TWILIO_SMS_TEMPLATE=sms_internal_alerts`
- Trial SMS uses Twilio’s fixed template text (not custom violence details)
- Full alert details are always in local `alerts/` and optional Supabase

## Supabase logging (every detection)

1. Create a Supabase project → **SQL Editor** → run **`supabase/schema.sql`**
2. In `.env`:
   ```env
   SUPABASE_LOGGING=true
   SUPABASE_URL=https://YOUR_REF.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=eyJ...
   ```
3. Verify:
   ```bash
   python3 setup_supabase.py
   python3 violence_monitor.py --test-log
   ```
4. Check **Table Editor → violence_alerts** for new rows.

On Render, set the same vars + `SUPABASE_LOGGING=true`.

## 8. Troubleshooting

| Issue | Fix |
|-------|-----|
| No SMS | Check `SMS_TO`, Twilio credentials, trial balance |
| Invalid template name | Use `sms_internal_alerts` for India trial |
| Camera unreachable | Server must reach camera IP (VPN/LAN/port forward) |
| Supabase insert failed / 404 | Run `supabase/schema.sql` in new project's SQL Editor |
