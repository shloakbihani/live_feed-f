"""Fine-tune the latest violence classifier on ml-model/new_data.

Starts from best_action_ft.pt (the struggle-clip fine-tune). The original
best.pt and the earlier daycare checkpoint are not the starting point
and are not overwritten. Only the classification head is trained.
"""

from __future__ import annotations

from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).parent
WEIGHTS = ROOT / "violence_yolov8n_cls-4" / "weights" / "best_action_ft.pt"


def device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "0"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def main() -> None:
    if not WEIGHTS.is_file():
        raise SystemExit(f"Missing latest fine-tune: {WEIGHTS}")
    if WEIGHTS.name == "best.pt":
        raise SystemExit("Refusing to start from the original base weights")

    print(f"Starting from {WEIGHTS}")
    model = YOLO(str(WEIGHTS))
    names = dict(getattr(model, "names", {}))
    print(f"Loaded classes: {names}")
    model.train(
        data=str(ROOT / "dataset_actions"),
        epochs=8,
        patience=3,
        imgsz=224,
        batch=16,
        freeze=9,
        lr0=0.0003,
        lrf=0.1,
        optimizer="AdamW",
        weight_decay=0.0005,
        dropout=0.0,
        device=device(),
        workers=2,
        project=str(ROOT / "runs"),
        name="violence_newdata_ft",
        exist_ok=True,
        pretrained=True,
        verbose=True,
        plots=True,
    )


if __name__ == "__main__":
    main()
