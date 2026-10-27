"""Build a fine-tune set from ml-model/new_data.

new_data/violence holds the unsafe clips.
new_data/non-violence holds safe frames, including false alarms.
Frames are sampled twice per second. Safe training frames are repeated
so a few photos are not drowned out by the longer clips.
"""

from __future__ import annotations

import random
import shutil
from pathlib import Path

import cv2

ROOT = Path(__file__).parent
CLIPS = ROOT / "new_data"
DST = ROOT / "dataset_actions"
SEED = 0
VAL_FRACTION = 0.2
SAMPLE_FPS = 2.0
SAFE_REPEAT = 6


def downscale(frame, long_side: int = 640):
    height, width = frame.shape[:2]
    longest = max(height, width)
    if longest <= long_side:
        return frame
    scale = long_side / longest
    return cv2.resize(
        frame,
        (max(1, int(width * scale)), max(1, int(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def sample_video(video: Path) -> list:
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, int(round(fps / SAMPLE_FPS)))
    frames = []
    index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if index % step == 0:
            frames.append(downscale(frame))
        index += 1
    cap.release()
    return frames


def unique_images(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    chosen = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            chosen.append(path)
    return chosen


def reset_split() -> None:
    if DST.exists():
        shutil.rmtree(DST)
    for split in ("train", "val"):
        for label in ("non_violence", "violence"):
            (DST / split / label).mkdir(parents=True)


def write_jpg(frame, dest: Path) -> None:
    cv2.imwrite(str(dest), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])


def safe_sources() -> list[Path]:
    found: list[Path] = []
    for name in ("non-violence", "non_violence"):
        found.extend(unique_images(CLIPS / name))
    return found


def main() -> None:
    random.seed(SEED)
    reset_split()

    safe = safe_sources()
    if len(safe) < 4:
        raise SystemExit(f"Need safe images in {CLIPS / 'non-violence'}")
    order = safe[:]
    random.shuffle(order)
    val_n = max(1, int(round(len(order) * VAL_FRACTION)))
    val_safe = set(order[:val_n])
    for path in safe:
        split = "val" if path in val_safe else "train"
        dest = DST / split / "non_violence" / f"safe_{path.name}"
        if dest.exists():
            continue
        try:
            dest.hardlink_to(path)
        except OSError:
            shutil.copy2(path, dest)
        if split == "train":
            for copy_i in range(1, SAFE_REPEAT):
                copy = DST / "train" / "non_violence" / f"safe_{path.stem}_r{copy_i}{path.suffix.lower()}"
                if copy.suffix != ".jpg":
                    copy = copy.with_suffix(".jpg")
                try:
                    copy.hardlink_to(dest)
                except OSError:
                    shutil.copy2(dest, copy)

    videos = sorted((CLIPS / "violence").glob("*.mp4"))
    if not videos:
        videos = sorted(CLIPS.glob("*.mp4"))
    if not videos:
        raise SystemExit(f"No videos in {CLIPS / 'violence'}")

    for video in videos:
        frames = sample_video(video)
        if not frames:
            raise SystemExit(f"Could not read frames from {video.name}")
        for index, frame in enumerate(frames):
            split = "val" if index % 5 == 0 else "train"
            write_jpg(frame, DST / split / "violence" / f"{video.stem}_{index:03d}.jpg")
        print(f"{video.name}: {len(frames)} frames @ {SAMPLE_FPS:.0f} fps")

    def count(split: str, label: str) -> int:
        return len(list((DST / split / label).glob("*")))

    print(
        "train",
        f"non_violence={count('train', 'non_violence')}",
        f"violence={count('train', 'violence')}",
    )
    print(
        "val",
        f"non_violence={count('val', 'non_violence')}",
        f"violence={count('val', 'violence')}",
    )


if __name__ == "__main__":
    main()
