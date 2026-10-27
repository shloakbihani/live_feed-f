"""Build a fine-tune set from the three new unsafe clips.

Frames are taken twice per second so the struggle is learned without
keeping every near-duplicate frame. Calm daycare photos stay in the set
so the model does not call the empty room unsafe.
"""

from __future__ import annotations

import random
import shutil
from pathlib import Path

import cv2

ROOT = Path(__file__).parent
SRC = ROOT / "data"
CLIPS = ROOT / "new_data"
DST = ROOT / "dataset_actions"
SEED = 0
VAL_FRACTION = 0.2
SAMPLE_FPS = 2.0
VIOLENCE_REPEAT = 2


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
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
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


def main() -> None:
    random.seed(SEED)
    reset_split()

    safe = unique_images(SRC / "non_violence")
    if len(safe) < 10:
        raise SystemExit(f"Need calm images in {SRC / 'non_violence'}")
    order = safe[:]
    random.shuffle(order)
    val_n = max(1, int(len(order) * VAL_FRACTION))
    val_safe = set(order[:val_n])
    for path in safe:
        split = "val" if path in val_safe else "train"
        dest = DST / split / "non_violence" / path.name
        if not dest.exists():
            dest.hardlink_to(path)

    videos = sorted(CLIPS.glob("*.mp4"))
    if len(videos) < 1:
        raise SystemExit(f"No videos in {CLIPS}")

    train_v = val_v = 0
    for video in videos:
        frames = sample_video(video)
        if not frames:
            raise SystemExit(f"Could not read frames from {video.name}")
        for index, frame in enumerate(frames):
            split = "val" if index % 5 == 0 else "train"
            name = f"{video.stem}_{index:03d}.jpg"
            write_jpg(frame, DST / split / "violence" / name)
            if split == "train":
                train_v += 1
                for copy_i in range(1, VIOLENCE_REPEAT):
                    write_jpg(frame, DST / "train" / "violence" / f"{video.stem}_{index:03d}_r{copy_i}.jpg")
                    train_v += 1
            else:
                val_v += 1
        print(f"{video.name}: {len(frames)} frames @ {SAMPLE_FPS:.0f} fps")

    for path in unique_images(SRC / "violence"):
        dest = DST / "train" / "violence" / f"earlier_{path.name}"
        if not dest.exists():
            dest.hardlink_to(path)
            train_v += 1

    def count(split: str, label: str) -> int:
        return len(list((DST / split / label).glob("*")))

    print(
        "train",
        f"non_violence={count('train', 'non_violence')}",
        f"violence={count('train', 'violence')} (written {train_v})",
    )
    print(
        "val",
        f"non_violence={count('val', 'non_violence')}",
        f"violence={count('val', 'violence')} (written {val_v})",
    )


if __name__ == "__main__":
    main()
