"""
Live Violence Detection on CP Plus Camera Feed.

Pulls RTSPS frames via ffmpeg, runs the YOLOv8 violence classifier,
overlays results, and saves alert clips/snapshots when violence is detected.

Usage:
    python3 violence_monitor.py                      # live window + alerts
    python3 violence_monitor.py --channel 1
    python3 violence_monitor.py --conf 0.7           # raise alert threshold
    python3 violence_monitor.py --every 5            # infer every 5th frame
    python3 violence_monitor.py --save-alerts        # save clips on violence
    python3 violence_monitor.py --headless --save-alerts
    python3 violence_monitor.py --weights path/to/best.pt
"""

from __future__ import annotations

import argparse
import collections
import csv
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from config import (
    ALERT_COOLDOWN_SEC,
    CAMERA_CHANNEL,
    CAMERA_IP,
    CAMERA_SUBTYPE,
    CONFIRM_HITS,
    CONFIRM_WINDOW,
    DAYCARE_NAME,
    DECODE_FPS,
    DECODE_WIDTH,
    DEPLOY_HEADLESS,
    INFER_PAUSE_AFTER_ALERT_SEC,
    PORTAL_URL,
    SAVE_CLIPS,
    VIOLENCE_CONF,
    VIOLENCE_EVERY_N,
)
from cloud_store import publish_detection, storage_configured
from notifier import AlertEvent, AlertNotifier, build_notifier_from_env
from stream_utils import (
    FFMPEG,
    build_rtsp_url,
    log_stream_failure,
    open_ffmpeg_pipe,
    probe_stream,
)
from violence_detector import DEFAULT_WEIGHTS, ViolenceDetector, ViolenceResult


def draw_overlay(
    frame: np.ndarray,
    result: ViolenceResult | None,
    fps: float,
    alert_active: bool,
) -> np.ndarray:
    disp = frame.copy()
    h, w = disp.shape[:2]

    # Status bar
    if result is None:
        color = (180, 180, 180)
        text = "Warming up..."
    elif result.is_violence:
        color = (0, 0, 255)
        text = f"VIOLENCE DETECTED  {result.confidence:.0%}"
    else:
        color = (0, 200, 0)
        text = f"SAFE  {result.label}  {result.confidence:.0%}"

    bar_h = max(48, h // 25)
    cv2.rectangle(disp, (0, 0), (w, bar_h), color, -1)
    cv2.putText(
        disp, text, (16, int(bar_h * 0.7)),
        cv2.FONT_HERSHEY_SIMPLEX, max(0.7, h / 900), (255, 255, 255), 2, cv2.LINE_AA,
    )

    # Meta
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(
        disp, f"{ts}  |  {fps:.1f} FPS  |  {CAMERA_IP}",
        (16, bar_h + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA,
    )

    if result is not None:
        y = bar_h + 55
        for name, score in result.scores.items():
            cv2.putText(
                disp, f"{name}: {score:.1%}",
                (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1, cv2.LINE_AA,
            )
            y += 22

    if alert_active:
        cv2.rectangle(disp, (8, 8), (w - 8, h - 8), (0, 0, 255), 6)
        cv2.putText(
            disp, "ALERT", (w - 160, bar_h + 40),
            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3, cv2.LINE_AA,
        )

    return disp


class AlertManager:
    """Saves snapshots when violence is confirmed; uploads to Cloudinary off-thread."""

    def __init__(
        self,
        out_dir: Path,
        cooldown_sec: float = 10.0,
        buffer_size: int = 20,
        notifier: AlertNotifier | None = None,
        channel: int = 1,
        save_clips: bool = False,
    ):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.cooldown_sec = cooldown_sec
        self.buffer: collections.deque = collections.deque(maxlen=buffer_size)
        self.last_alert_time = 0.0
        self.notifier = notifier
        self.channel = channel
        self.save_clips = save_clips
        self.log_path = self.out_dir / "alerts.csv"
        if not self.log_path.exists():
            with open(self.log_path, "w", newline="") as f:
                csv.writer(f).writerow(
                    ["timestamp", "confidence", "label", "snapshot", "clip"]
                )

    def push(self, frame: np.ndarray):
        self.buffer.append(frame)

    def maybe_alert(
        self,
        result: ViolenceResult,
        snapshot: np.ndarray | None = None,
    ) -> Path | None:
        now = time.time()
        if not result.is_violence:
            return None
        if now - self.last_alert_time < self.cooldown_sec:
            return None

        self.last_alert_time = now
        detected_at = datetime.now().astimezone()
        stamp = detected_at.strftime("%Y%m%d_%H%M%S")
        snap_path = self.out_dir / f"alert_{stamp}.jpg"
        clip_path = self.out_dir / f"alert_{stamp}.mp4"
        # Prefer the highest-confidence frame from the confirmation window.
        latest = snapshot if snapshot is not None else (
            self.buffer[-1] if self.buffer else None
        )

        if latest is not None:
            cv2.imwrite(str(snap_path), latest, [int(cv2.IMWRITE_JPEG_QUALITY), 70])

        if self.save_clips and len(self.buffer) >= 5:
            h, w = self.buffer[0].shape[:2]
            writer = cv2.VideoWriter(
                str(clip_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                8.0,
                (w, h),
            )
            for f in self.buffer:
                writer.write(f)
            writer.release()
        else:
            clip_path = Path("")

        with open(self.log_path, "a", newline="") as f:
            csv.writer(f).writerow([
                detected_at.isoformat(timespec="seconds"),
                f"{result.confidence:.4f}",
                result.label,
                snap_path.name,
                clip_path.name if clip_path else "",
            ])

        print(
            f"\n  ALERT saved → {snap_path.name}  "
            f"(highest-confidence frame {result.confidence:.0%})"
            + (f" + {clip_path.name}" if clip_path else "")
        )

        frame_copy = latest.copy() if latest is not None else None

        def _publish():
            snapshot_url = None
            public_id = None
            if frame_copy is not None:
                published = publish_detection(
                    frame_copy,
                    detected_at,
                    result.confidence,
                    result.label,
                    self.channel,
                )
                cloud = published.get("storage") or {}
                snapshot_url = cloud.get("url")
                public_id = cloud.get("public_id")
            if self.notifier:
                self.notifier.notify(AlertEvent(
                    detected_at=detected_at,
                    confidence=result.confidence,
                    label=result.label,
                    camera_ip=CAMERA_IP,
                    channel=self.channel,
                    snapshot_path=snap_path.name,
                    clip_path=clip_path.name if clip_path else None,
                    snapshot_url=snapshot_url,
                    cloudinary_public_id=public_id,
                ))

        threading.Thread(target=_publish, daemon=True).start()
        return snap_path


def run_monitor(
    url: str,
    info: dict,
    detector: ViolenceDetector,
    every_n: int = 4,
    save_alerts: bool = True,
    headless: bool = False,
    display_scale: float = 0.5,
    notifier: AlertNotifier | None = None,
    channel: int = 1,
    cooldown_sec: float = ALERT_COOLDOWN_SEC,
    pause_after_alert_sec: float = INFER_PAUSE_AFTER_ALERT_SEC,
    decode_width: int = DECODE_WIDTH,
    decode_fps: float = DECODE_FPS,
    confirm_hits: int = CONFIRM_HITS,
    confirm_window: int = CONFIRM_WINDOW,
):
    src_w, src_h = info["width"], info["height"]
    if src_w == 0 or src_h == 0:
        print("ERROR: Could not determine stream resolution from ffprobe.")
        sys.exit(1)

    alert_mgr = (
        AlertManager(
            Path("alerts"),
            notifier=notifier,
            channel=channel,
            cooldown_sec=cooldown_sec,
            save_clips=SAVE_CLIPS,
            buffer_size=20,
        )
        if save_alerts else None
    )

    latest: ViolenceResult | None = None
    frame_count = 0
    infer_count = 0
    skipped_infer = 0
    start = time.time()
    confirm_hits = max(1, confirm_hits)
    confirm_window = max(confirm_hits, confirm_window)
    # (is_violence, result, frame) for the last N inferences
    hit_window: collections.deque = collections.deque(maxlen=confirm_window)
    alert_active = False
    pause_until = 0.0
    last_pause_log = 0.0

    print(f"\nSource: {src_w}x{src_h} {info['codec'].upper()} @ {info['fps_str']}")
    print(
        f"Decode ≤{decode_width}px @ {decode_fps:.0f} fps  |  "
        f"infer every {every_n} frame(s)  |  threshold={detector.conf_threshold:.0%}"
    )
    window_sec = confirm_window * every_n / decode_fps if decode_fps else 0
    print(
        f"Confirm {confirm_hits} of last {confirm_window} inferences "
        f"(~{window_sec:.1f}s window)"
    )
    print(f"ML pause after alert: {pause_after_alert_sec:.0f}s (Pi cooldown)")
    print("Press 'q' to quit, 's' for snapshot\n")

    reconnects = 0
    while True:
        proc, stderr_tail, w, h = open_ffmpeg_pipe(
            url, src_w, src_h, out_width=decode_width, out_fps=decode_fps,
        )
        frame_size = w * h * 3
        try:
            while True:
                raw = proc.stdout.read(frame_size)
                if len(raw) != frame_size:
                    reconnects += 1
                    log_stream_failure(proc, stderr_tail, len(raw), frame_size)
                    if reconnects == 1 or reconnects % 10 == 0:
                        print(f"Stream interrupted — reconnecting in 2s... (attempt {reconnects})")
                    else:
                        print("Stream interrupted — reconnecting in 2s...")
                    time.sleep(2)
                    break

                frame = np.frombuffer(raw, dtype=np.uint8).reshape((h, w, 3))
                frame_count += 1
                now = time.time()
                paused = now < pause_until

                if alert_mgr and not paused:
                    # Already a small decoded frame — no extra copy.
                    alert_mgr.push(frame)

                if paused:
                    skipped_infer += 1
                    remaining = int(pause_until - now)
                    if now - last_pause_log >= 60:
                        print(f"  ML paused after alert — resume in {remaining}s")
                        last_pause_log = now
                    alert_active = False
                    hit_window.clear()
                elif frame_count % every_n == 0:
                    latest = detector.predict(frame)
                    infer_count += 1

                    snap = frame.copy() if latest.is_violence else None
                    hit_window.append((latest.is_violence, latest, snap))
                    hits = sum(1 for is_v, _, _ in hit_window if is_v)
                    alert_active = hits >= confirm_hits

                    if alert_active and alert_mgr:
                        best_hit_result = None
                        best_hit_frame = None
                        for is_v, res, frm in hit_window:
                            if not is_v or res is None:
                                continue
                            if (
                                best_hit_result is None
                                or res.confidence > best_hit_result.confidence
                            ):
                                best_hit_result = res
                                best_hit_frame = frm
                        fired = alert_mgr.maybe_alert(
                            best_hit_result or latest,
                            snapshot=best_hit_frame,
                        )
                        if fired is not None and pause_after_alert_sec > 0:
                            pause_until = time.time() + pause_after_alert_sec
                            last_pause_log = time.time()
                            hit_window.clear()
                            print(
                                f"  ML paused for {pause_after_alert_sec:.0f}s "
                                "to keep the device cool"
                            )

                elapsed = now - start
                fps = frame_count / elapsed if elapsed > 0 else 0

                if not headless:
                    disp = draw_overlay(frame, latest, fps, alert_active)
                    if paused:
                        cv2.putText(
                            disp, "ML PAUSED (cooldown)",
                            (16, disp.shape[0] - 24),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2, cv2.LINE_AA,
                        )
                    if display_scale != 1.0:
                        disp = cv2.resize(
                            disp, None, fx=display_scale, fy=display_scale,
                            interpolation=cv2.INTER_AREA,
                        )
                    cv2.imshow("Violence Monitor — CP Plus", disp)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        raise KeyboardInterrupt
                    elif key == ord("s"):
                        fn = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                        cv2.imwrite(fn, frame)
                        print(f"Snapshot: {fn}")
                elif frame_count % 25 == 0 and not paused:
                    status = latest or "warming up"
                    print(
                        f"  frames={frame_count}  infer={infer_count}  "
                        f"skipped={skipped_infer}  fps={fps:.1f}  {status}"
                    )

        except KeyboardInterrupt:
            break
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()

    if not headless:
        cv2.destroyAllWindows()

    print(f"\nDone. Frames={frame_count}  Inferences={infer_count}  Skipped={skipped_infer}")
    if alert_mgr:
        print(f"Alerts folder: {alert_mgr.out_dir.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="Live Violence Detection on CP Plus feed")
    parser.add_argument("--channel", type=int, default=CAMERA_CHANNEL)
    parser.add_argument("--subtype", type=int, default=CAMERA_SUBTYPE, choices=[0, 1],
                        help="0=main HD (slower), 1=sub-stream (recommended for ML)")
    parser.add_argument("--weights", default=str(DEFAULT_WEIGHTS))
    parser.add_argument("--conf", type=float, default=VIOLENCE_CONF,
                        help="Violence confidence threshold")
    parser.add_argument("--every", type=int, default=VIOLENCE_EVERY_N,
                        help="Run inference every N frames")
    parser.add_argument("--confirm", type=int, default=CONFIRM_HITS,
                        help="Violence inferences required in the confirm window (default 8)")
    parser.add_argument("--confirm-window", type=int, default=CONFIRM_WINDOW,
                        help="Recent inferences to count (default 10; 8 of 10)")
    parser.add_argument("--cooldown", type=float, default=ALERT_COOLDOWN_SEC,
                        help="Seconds between SMS/portal alerts (default 300)")
    parser.add_argument("--pause", type=float, default=INFER_PAUSE_AFTER_ALERT_SEC,
                        help="Seconds to skip ML after an alert (default 900)")
    parser.add_argument("--decode-width", type=int, default=DECODE_WIDTH,
                        help="Max decode width in ffmpeg (default 416)")
    parser.add_argument("--decode-fps", type=float, default=DECODE_FPS,
                        help="Decode frame rate (default 5)")
    parser.add_argument("--device", default=None, help="cpu / mps / 0")
    parser.add_argument("--save-alerts", action="store_true", default=True)
    parser.add_argument("--no-alerts", action="store_true")
    parser.add_argument("--headless", action="store_true",
                        help="No display window (default from DEPLOY_HEADLESS in .env)")
    parser.add_argument("--scale", type=float, default=0.5,
                        help="Display scale factor (default 0.5)")
    parser.add_argument("--no-sms", action="store_true",
                        help="Skip SMS notifications")
    parser.add_argument("--test-sms", action="store_true",
                        help="Send test SMS + log to Supabase, then exit")
    parser.add_argument("--test-log", action="store_true",
                        help="Log a test detection to Supabase only (no SMS)")
    parser.add_argument("--probe-only", action="store_true",
                        help="Test camera connection and print stream info, then exit")
    parser.add_argument("--no-whatsapp", action="store_true",
                        help="Deprecated alias for --no-sms")
    parser.add_argument("--test-whatsapp", action="store_true",
                        help="Deprecated alias for --test-sms")
    args = parser.parse_args()

    if args.no_whatsapp:
        args.no_sms = True
    if args.test_whatsapp:
        args.test_sms = True

    headless = args.headless or DEPLOY_HEADLESS

    print("=" * 60)
    print("  Violence Detection — Live Monitor")
    print(f"  Camera: {CAMERA_IP}  Channel: {args.channel}")
    print(f"  Weights: {args.weights}")
    print(f"  Mode: {'headless (deploy)' if headless else 'display'}")
    print("=" * 60)

    notifier = None if args.no_alerts else build_notifier_from_env()
    if notifier and args.no_sms:
        notifier.sms_enabled = False
        notifier._twilio = None

    if args.test_log or args.test_sms:
        if notifier is None or not notifier.enabled:
            print("ERROR: Set SUPABASE_LOGGING=true + Supabase keys in .env")
            print("       (and Twilio keys for --test-sms)")
            sys.exit(1)
        if args.test_log:
            notifier.sms_enabled = False
            notifier._twilio = None
        result = notifier.notify(AlertEvent(
            detected_at=datetime.now().astimezone(),
            confidence=0.99,
            label="violence",
            camera_ip=CAMERA_IP,
            channel=args.channel,
            snapshot_path="test",
        ))
        print("Test result:", result)
        sys.exit(0 if result.get("ok") else 1)

    if not Path(FFMPEG).exists() and not shutil.which("ffmpeg"):
        print("ERROR: ffmpeg not found. Install with: brew install ffmpeg")
        sys.exit(1)

    print("\nLoading model...")
    detector = ViolenceDetector(
        weights=args.weights,
        conf_threshold=args.conf,
        device=args.device,
    )
    print(f"  Classes: {detector.names}")
    print(f"  Threshold: {detector.conf_threshold:.0%}")
    print(f"  Confirm: {max(1, args.confirm)} of last {max(1, args.confirm_window)}")
    print(f"  Daycare: {DAYCARE_NAME or CAMERA_IP}")
    if storage_configured():
        print("  Snapshots: Supabase Storage")
    else:
        print("  Snapshots: not configured (set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)")
    if PORTAL_URL:
        print(f"  Portal: {PORTAL_URL}")
    if notifier and notifier.enabled:
        if notifier._supabase:
            print("  Supabase: logging enabled")
        if notifier.sms_enabled:
            print(f"  SMS: enabled → {', '.join(notifier.recipients)}")
        elif not notifier._supabase:
            print("  Alerts: portal only")
    else:
        print("  SMS/Supabase logging: off (snapshots and portal still used if configured)")

    url = build_rtsp_url(args.channel, args.subtype)
    print("\nConnecting to camera...")
    info = probe_stream(url)
    if not info:
        print("ERROR: Could not open stream. Check network / credentials.")
        print("  Tips: ensure port 554 is reachable from Render; use CAMERA_SUBTYPE=1;")
        print("  verify CAMERA_PASS in Render (special chars like $ must match exactly).")
        sys.exit(1)
    print(f"  Connected: {info['width']}x{info['height']} {info['codec']}")

    if args.probe_only:
        proc, stderr_tail, pw, ph = open_ffmpeg_pipe(
            url, info["width"], info["height"],
            out_width=args.decode_width, out_fps=args.decode_fps,
        )
        frame_size = pw * ph * 3
        raw = proc.stdout.read(frame_size)
        proc.terminate()
        if len(raw) == frame_size:
            print(f"  First frame: OK ({pw}x{ph})")
            sys.exit(0)
        log_stream_failure(proc, stderr_tail, len(raw), frame_size)
        print("ERROR: Connected but could not read a full video frame.")
        sys.exit(1)

    run_monitor(
        url=url,
        info=info,
        detector=detector,
        every_n=max(1, args.every),
        save_alerts=not args.no_alerts,
        headless=headless,
        display_scale=args.scale,
        notifier=notifier,
        channel=args.channel,
        cooldown_sec=args.cooldown,
        pause_after_alert_sec=args.pause,
        decode_width=args.decode_width,
        decode_fps=args.decode_fps,
        confirm_hits=max(1, args.confirm),
        confirm_window=max(1, args.confirm_window),
    )


if __name__ == "__main__":
    main()
