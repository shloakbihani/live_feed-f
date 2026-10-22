"""SQLite store for daycare tenants and detections (web service only)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from werkzeug.security import check_password_hash, generate_password_hash

from config import DATA_DIR, DAYCARE_TZ

DB_PATH = DATA_DIR / "portal.db"


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                camera_ip TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                daycare_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_ip TEXT NOT NULL,
                daycare_name TEXT NOT NULL,
                detected_at TEXT NOT NULL,
                confidence REAL NOT NULL,
                label TEXT NOT NULL,
                channel INTEGER NOT NULL DEFAULT 1,
                snapshot_url TEXT,
                cloudinary_public_id TEXT, -- Supabase Storage object path
                saved INTEGER NOT NULL DEFAULT 0,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS detections_camera_idx
                ON detections (camera_ip, detected_at DESC);
            CREATE INDEX IF NOT EXISTS detections_expiry_idx
                ON detections (saved, expires_at);

            CREATE TABLE IF NOT EXISTS push_subscriptions (
                endpoint TEXT PRIMARY KEY,
                camera_ip TEXT NOT NULL,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                user_agent TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS push_camera_idx
                ON push_subscriptions (camera_ip);

            CREATE TABLE IF NOT EXISTS app_flags (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )


# Labeled unsafe frames shown once in Archive. A delete stays deleted.
ARCHIVE_SAMPLES = (
    ("alert_20260721_174427.jpg", "2026-07-21T17:44:27+05:30", 0.82),
    ("alert_20260811_160522.jpg", "2026-08-11T16:05:22+05:30", 0.76),
    ("alert_20260811_160548.jpg", "2026-08-11T16:05:48+05:30", 0.74),
    ("alert_20260924_173127.jpg", "2026-09-24T17:31:27+05:30", 0.85),
)


def seed_archive_samples(camera_ip: str, daycare_name: str) -> int:
    """Add the sample archive frames once for this centre."""
    camera_ip = camera_ip.strip()
    flag = f"archive_samples:{camera_ip}"
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        already = conn.execute(
            "SELECT 1 FROM app_flags WHERE key = ?",
            (flag,),
        ).fetchone()
        if already:
            return 0
        conn.execute(
            "INSERT INTO app_flags (key, value) VALUES (?, '1')",
            (flag,),
        )
        created = datetime.now().astimezone().isoformat()
        for filename, when, confidence in ARCHIVE_SAMPLES:
            detected = datetime.fromisoformat(when)
            conn.execute(
                """
                INSERT INTO detections (
                    camera_ip, daycare_name, detected_at, confidence, label, channel,
                    snapshot_url, cloudinary_public_id, saved, expires_at, created_at
                ) VALUES (?, ?, ?, ?, 'violence', 1, ?, '', 1, ?, ?)
                """,
                (
                    camera_ip,
                    daycare_name,
                    detected.isoformat(),
                    confidence,
                    f"/static/archive/{filename}",
                    end_of_local_day(detected).isoformat(),
                    created,
                ),
            )
        return len(ARCHIVE_SAMPLES)


def upsert_tenant(camera_ip: str, password: str, daycare_name: str) -> None:
    now = datetime.now().astimezone().isoformat()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO tenants (camera_ip, password_hash, daycare_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(camera_ip) DO UPDATE SET
                password_hash = excluded.password_hash,
                daycare_name = excluded.daycare_name
            """,
            (camera_ip.strip(), generate_password_hash(password), daycare_name.strip(), now),
        )


def get_tenant(camera_ip: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM tenants WHERE camera_ip = ?",
            (camera_ip.strip(),),
        ).fetchone()


def authenticate(camera_ip: str, password: str) -> sqlite3.Row | None:
    tenant = get_tenant(camera_ip)
    if tenant is None:
        return None
    if not check_password_hash(tenant["password_hash"], password):
        return None
    return tenant


def end_of_local_day(now: datetime | None = None) -> datetime:
    tz = ZoneInfo(DAYCARE_TZ)
    local = (now or datetime.now(tz)).astimezone(tz)
    next_day = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return next_day


def insert_detection(payload: dict) -> int:
    camera_ip = str(payload["camera_ip"]).strip()
    tenant = get_tenant(camera_ip)
    daycare_name = (
        (tenant["daycare_name"] if tenant else None)
        or payload.get("daycare_name")
        or camera_ip
    )
    detected_raw = payload.get("detected_at") or datetime.now().astimezone().isoformat()
    try:
        detected_at = datetime.fromisoformat(str(detected_raw).replace("Z", "+00:00"))
    except ValueError:
        detected_at = datetime.now().astimezone()
    expires = end_of_local_day(detected_at)
    created = datetime.now().astimezone().isoformat()
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO detections (
                camera_ip, daycare_name, detected_at, confidence, label, channel,
                snapshot_url, cloudinary_public_id, saved, expires_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                camera_ip,
                daycare_name,
                detected_at.isoformat(),
                float(payload.get("confidence") or 0),
                str(payload.get("label") or "violence"),
                int(payload.get("channel") or 1),
                payload.get("snapshot_url") or "",
                payload.get("cloudinary_public_id") or "",
                expires.isoformat(),
                created,
            ),
        )
        return int(cur.lastrowid)


def list_detections(camera_ip: str, saved_only: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM detections WHERE camera_ip = ?"
    args: list = [camera_ip]
    if saved_only:
        sql += " AND saved = 1"
    sql += " ORDER BY detected_at DESC"
    with connect() as conn:
        return conn.execute(sql, args).fetchall()


def get_detection(det_id: int, camera_ip: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM detections WHERE id = ? AND camera_ip = ?",
            (det_id, camera_ip),
        ).fetchone()


def set_saved(det_id: int, camera_ip: str, saved: bool) -> sqlite3.Row | None:
    with connect() as conn:
        conn.execute(
            "UPDATE detections SET saved = ? WHERE id = ? AND camera_ip = ?",
            (1 if saved else 0, det_id, camera_ip),
        )
        return get_detection(det_id, camera_ip)


def expired_unsaved() -> list[sqlite3.Row]:
    now = datetime.now().astimezone().isoformat()
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM detections WHERE saved = 0 AND expires_at <= ?",
            (now,),
        ).fetchall()


def delete_detection(det_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM detections WHERE id = ?", (det_id,))


def upsert_push_subscription(
    camera_ip: str,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str = "",
) -> None:
    now = datetime.now().astimezone().isoformat()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO push_subscriptions (
                endpoint, camera_ip, p256dh, auth, user_agent, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                camera_ip = excluded.camera_ip,
                p256dh = excluded.p256dh,
                auth = excluded.auth,
                user_agent = excluded.user_agent,
                updated_at = excluded.updated_at
            """,
            (endpoint, camera_ip.strip(), p256dh, auth, user_agent[:240], now, now),
        )


def delete_push_subscription(endpoint: str, camera_ip: str | None = None) -> None:
    with connect() as conn:
        if camera_ip:
            conn.execute(
                "DELETE FROM push_subscriptions WHERE endpoint = ? AND camera_ip = ?",
                (endpoint, camera_ip.strip()),
            )
        else:
            conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))


def list_push_subscriptions(camera_ip: str) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM push_subscriptions WHERE camera_ip = ?",
            (camera_ip.strip(),),
        ).fetchall()


def bootstrap_tenants(raw: str) -> int:
    """Register tenants from WEB_TENANTS=ip|password|Name;ip|password|Name."""
    if not raw.strip():
        return 0
    count = 0
    for chunk in raw.replace("\n", ";").split(";"):
        parts = [p.strip() for p in chunk.split("|")]
        if len(parts) < 3:
            continue
        ip, password, name = parts[0], parts[1], "|".join(parts[2:]).strip()
        if not ip or not password or not name:
            continue
        upsert_tenant(ip, password, name)
        count += 1
        print(f"  [web] tenant ready: {name} ({ip})")
    return count
