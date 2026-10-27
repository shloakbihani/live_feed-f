#!/usr/bin/env python3
"""Open a window with the live camera and the current model prediction.

This does not save alerts, email anyone, or post to the dashboard.
Press q to quit, s to save the current frame.

    python3 live_preview.py
    python3 live_preview.py --weights violence_yolov8n_cls-4/weights/best_newdata_ft.pt
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime

import cv2
import numpy as np

from config import (
    CAMERA_CHANNEL,
    CAMERA_IP,
    CAMERA_SUBTYPE,
    DECODE_FPS,
    DECODE_WIDTH,
    VIOLENCE_CONF,
    VIOLENCE_WEIGHTS,
)
from stream_utils import (
    build_rtsp_url,
    log_stream_failure,
    open_ffmpeg_pipe,
    probe_stream,
)
from violence_detector import ViolenceDetector
from violence_monitor import draw_overlay


def main() -> None:
    parser = argparse.ArgumentParser(description="Live camera preview with model scores")
    parser.add_argument("--channel", type=int, default=CAMERA_CHANNEL)
    parser.add_argument("--subtype", type=int, default=CAMERA_SUBTYPE, choices=[0, 1])
    parser.add_argument("--weights", default=VIOLENCE_WEIGHTS)
    parser.add_argument("--conf", type=float, default=VIOLENCE_CONF)
    parser.add_argument("--every", type=int, default=1, help="Run the model every N decoded frames")
    parser.add_argument("--decode-width", type=int, default=DECODE_WIDTH)
    parser.add_argument("--decode-fps", type=float, default=DECODE_FPS)
    parser.add_argument("--scale", type=float, default=2.0, help="Window size relative to the decoded frame")
    parser.add_argument("--device", default=None, help="cpu / mps / 0")
    args = parser.parse_args()

    print("Live preview — no alerts are sent")
    print(f"  Camera: {CAMERA_IP}  channel {args.channel}")
    print(f"  Weights: {args.weights}")
    detector = ViolenceDetector(args.weights, conf_threshold=args.conf, device=args.device)
    print(f"  Classes: {detector.names}")
    print("  Press q to quit, s to save a snapshot")

    url = build_rtsp_url(args.channel, args.subtype)
    info = probe_stream(url)
    if not info:
        raise SystemExit("Could not open the camera stream.")

    src_w, src_h = info["width"], info["height"]
    latest = None
    frame_count = 0
    infer_count = 0
    start = time.time()
    window = "Daycare live - model preview"

    while True:
        proc, stderr_tail, width, height = open_ffmpeg_pipe(
            url, src_w, src_h, out_width=args.decode_width, out_fps=args.decode_fps,
        )
        frame_size = width * height * 3
        try:
            while True:
                raw = proc.stdout.read(frame_size)
                if len(raw) != frame_size:
                    log_stream_failure(proc, stderr_tail, len(raw), frame_size)
                    print("Stream interrupted — reconnecting in 2s...")
                    time.sleep(2)
                    break

                frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3))
                frame_count += 1
                if frame_count % max(1, args.every) == 0:
                    latest = detector.predict(frame)
                    infer_count += 1

                elapsed = time.time() - start
                fps = frame_count / elapsed if elapsed else 0
                disp = draw_overlay(frame, latest, fps, alert_active=bool(latest and latest.is_violence))
                if args.scale != 1.0:
                    disp = cv2.resize(
                        disp, None, fx=args.scale, fy=args.scale, interpolation=cv2.INTER_LINEAR,
                    )
                cv2.imshow(window, disp)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    proc.terminate()
                    cv2.destroyAllWindows()
                    print(f"Done. Frames={frame_count}  Inferences={infer_count}")
                    return
                if key == ord("s"):
                    name = f"snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                    cv2.imwrite(name, frame)
                    print(f"Snapshot: {name}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    main()
