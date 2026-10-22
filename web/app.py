"""Daycare web dashboard.

Independent of the Pi ML service. Pi uploads frames to Supabase Storage and POSTs here.
Save / delete / midnight purge all run on this service.
Login: camera IP + camera password.
"""

from __future__ import annotations

from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

import db as store
import push
from storage_util import destroy_asset
from config import (
    DAYCARE_TZ,
    PORTAL_DEBUG,
    PORTAL_INGEST_KEY,
    PORTAL_PORT,
    PORTAL_SECRET_KEY,
    WEB_TENANTS,
)

_STATIC_DIR = Path(__file__).parent / "static"

app = Flask(__name__)
app.secret_key = PORTAL_SECRET_KEY
store.init_db()
store.bootstrap_tenants(WEB_TENANTS)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("camera_ip"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


def ingest_authorized() -> bool:
    key = request.headers.get("X-Ingest-Key") or request.args.get("key")
    return bool(PORTAL_INGEST_KEY) and key == PORTAL_INGEST_KEY


def remove_from_cloud_and_db(row) -> None:
    public_id = row["cloudinary_public_id"] if row else None
    if public_id:
        destroy_asset(public_id)
    store.delete_detection(int(row["id"]))


def purge_expired() -> int:
    rows = store.expired_unsaved()
    removed = 0
    for row in rows:
        remove_from_cloud_and_db(row)
        removed += 1
    return removed


@app.route("/sw.js")
def service_worker():
    response = send_from_directory(_STATIC_DIR, "sw.js", mimetype="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/health")
def health():
    return jsonify({"ok": True, "service": "daycare-dashboard"})


@app.route("/")
def home():
    if session.get("camera_ip"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        camera_ip = (request.form.get("camera_ip") or "").strip()
        password = request.form.get("password") or ""
        tenant = store.authenticate(camera_ip, password)
        if tenant is None:
            flash("Camera IP or password is incorrect.", "error")
            return render_template("login.html"), 401
        session["camera_ip"] = tenant["camera_ip"]
        session["daycare_name"] = tenant["daycare_name"]
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    purge_expired()
    camera_ip = session["camera_ip"]
    daycare_name = session.get("daycare_name") or camera_ip
    store.seed_archive_samples(camera_ip, daycare_name)
    rows = store.list_detections(camera_ip)
    saved = [r for r in rows if r["saved"]]
    today = [r for r in rows if not r["saved"]]
    critical = sum(1 for row in rows if float(row["confidence"]) >= 0.8)
    latest = rows[0] if rows else None
    return render_template(
        "dashboard.html",
        daycare_name=daycare_name,
        camera_ip=camera_ip,
        today=today,
        saved=saved,
        critical=critical,
        latest=latest,
        daycare_tz=DAYCARE_TZ,
    )


@app.route("/detections/<int:det_id>/save", methods=["POST"])
@login_required
def save_detection(det_id: int):
    row = store.set_saved(det_id, session["camera_ip"], True)
    if row is None:
        flash("Detection not found.", "error")
    else:
        flash("Detection saved. It will stay on the portal.", "ok")
    return redirect(url_for("dashboard"))


@app.route("/detections/<int:det_id>/unsave", methods=["POST"])
@login_required
def unsave_detection(det_id: int):
    row = store.set_saved(det_id, session["camera_ip"], False)
    if row is None:
        flash("Detection not found.", "error")
    else:
        flash("Save removed. This detection will be deleted at midnight if still unsaved.", "ok")
    return redirect(url_for("dashboard"))


@app.route("/detections/<int:det_id>/delete", methods=["POST"])
@login_required
def delete_detection(det_id: int):
    row = store.get_detection(det_id, session["camera_ip"])
    if row is None:
        flash("Detection not found.", "error")
        return redirect(url_for("dashboard"))
    public_id = row["cloudinary_public_id"]
    store.delete_detection(det_id)
    if public_id:
        destroy_asset(public_id)
        flash("Detection deleted from the portal and Supabase.", "ok")
    else:
        flash("Removed from the archive.", "ok")
    return redirect(url_for("dashboard"))


@app.route("/api/board")
def api_board():
    camera_ip = session.get("camera_ip")
    if not camera_ip:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    rows = store.list_detections(camera_ip)
    latest = rows[0] if rows else None
    return jsonify(
        {
            "ok": True,
            "pending": sum(1 for row in rows if not row["saved"]),
            "saved": sum(1 for row in rows if row["saved"]),
            "latest_id": int(latest["id"]) if latest else None,
        }
    )


@app.route("/api/detections", methods=["POST"])
def ingest_detection():
    if not ingest_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    camera_ip = str(payload.get("camera_ip") or "").strip()
    if not camera_ip:
        return jsonify({"ok": False, "error": "camera_ip required"}), 400
    tenant = store.get_tenant(camera_ip)
    if tenant is None:
        return jsonify({"ok": False, "error": "unknown camera_ip — register this daycare first"}), 404
    purge_expired()
    det_id = store.insert_detection(payload)
    daycare_name = tenant["daycare_name"] or camera_ip
    try:
        push_result = push.send_incident_push(
            camera_ip,
            daycare_name,
            payload.get("detected_at"),
        )
    except Exception as exc:
        print(f"  [push] incident send failed: {exc}")
        push_result = {"ok": False, "sent": 0, "error": str(exc)}
    return jsonify({"ok": True, "id": det_id, "push": push_result})


@app.route("/api/push/config")
@login_required
def push_config():
    return jsonify({"ok": True, "publicKey": push.public_key()})


@app.route("/api/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    payload = request.get_json(silent=True) or {}
    endpoint = str(payload.get("endpoint") or "").strip()
    keys = payload.get("keys") or {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    if not (endpoint and p256dh and auth):
        return jsonify({"ok": False, "error": "invalid subscription"}), 400
    store.upsert_push_subscription(
        session["camera_ip"],
        endpoint,
        p256dh,
        auth,
        request.headers.get("User-Agent") or "",
    )
    return jsonify({"ok": True})


@app.route("/api/push/unsubscribe", methods=["POST"])
@login_required
def push_unsubscribe():
    payload = request.get_json(silent=True) or {}
    endpoint = str(payload.get("endpoint") or "").strip()
    if not endpoint:
        return jsonify({"ok": False, "error": "endpoint required"}), 400
    store.delete_push_subscription(endpoint, session["camera_ip"])
    return jsonify({"ok": True})


@app.route("/api/push/test", methods=["POST"])
@login_required
def push_test():
    camera_ip = session["camera_ip"]
    daycare_name = session.get("daycare_name") or camera_ip
    result = push.send_incident_push(camera_ip, daycare_name, None)
    if result.get("sent", 0) == 0:
        return jsonify({
            "ok": False,
            "error": result.get("error") or "No browser is subscribed for this centre yet.",
        }), 400
    return jsonify({"ok": True, "sent": result["sent"]})


@app.route("/api/purge", methods=["POST", "GET"])
def api_purge():
    if not ingest_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    n = purge_expired()
    return jsonify({"ok": True, "removed": n})


def main() -> None:
    store.init_db()
    print(f"Daycare web dashboard → http://127.0.0.1:{PORTAL_PORT}")
    app.run(host="0.0.0.0", port=PORTAL_PORT, debug=PORTAL_DEBUG)


if __name__ == "__main__":
    main()
