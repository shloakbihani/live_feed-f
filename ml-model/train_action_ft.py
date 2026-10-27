"""Fine-tune the daycare model on the three new unsafe clips.

The backbone stays frozen. Only the classification head learns the new
struggle, starting from best_daycare_ft.pt so the calm-room behaviour
is the starting point. Original best.pt is not modified.
"""

from __future__ import annotations

from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).parent
WEIGHTS = ROOT / "violence_yolov8n_cls-4" / "weights" / "best_daycare_ft.pt"


def device() -> str:
    try:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def main() -> None:
    model = YOLO(str(WEIGHTS))
    model.train(
        data=str(ROOT / "dataset_actions"),
        epochs=12,
        patience=4,
        imgsz=224,
        batch=32,
        freeze=9,
        lr0=0.0004,
        lrf=0.1,
        optimizer="AdamW",
        weight_decay=0.0005,
        dropout=0.0,
        device=device(),
        workers=2,
        project=str(ROOT / "runs"),
        name="violence_action_ft",
        exist_ok=True,
        pretrained=True,
        verbose=True,
        plots=True,
    )


if __name__ == "__main__":
    main()
