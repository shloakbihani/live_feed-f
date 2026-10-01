"""
YOLOv8 violence classifier wrapper.

Model: pi/violence_yolov8n_cls-4/weights/best.pt
Classes: 0 = non_violence, 1 = violence
Input size: 224x224
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).parent
_REPO = _HERE.parent
_WEIGHTS_CANDIDATES = (
    _HERE / "violence_yolov8n_cls-4" / "weights" / "best.pt",
    _REPO / "violence_yolov8n_cls-4" / "weights" / "best.pt",  # old repo-root layout
)
DEFAULT_WEIGHTS = next(
    (p for p in _WEIGHTS_CANDIDATES if p.exists()),
    _WEIGHTS_CANDIDATES[0],
)

import cv2
import numpy as np
from ultralytics import YOLO

from config import TORCH_NUM_THREADS

os.environ.setdefault("OMP_NUM_THREADS", str(TORCH_NUM_THREADS))
os.environ.setdefault("MKL_NUM_THREADS", str(TORCH_NUM_THREADS))

try:
    import torch

    torch.set_num_threads(max(1, TORCH_NUM_THREADS))
except Exception:
    pass

INFER_SIZE = 224


@dataclass
class ViolenceResult:
    label: str
    confidence: float
    is_violence: bool
    scores: dict[str, float]

    def __str__(self) -> str:
        return f"{self.label} ({self.confidence:.1%})"


class PersonCounter:
    """Count people with the COCO YOLOv8n detector (class 0 = person)."""

    def __init__(
        self,
        weights: str | Path | None = None,
        conf_threshold: float = 0.40,
        device: str | None = None,
        imgsz: int = 320,
    ):
        weights_path = Path(weights) if weights else _HERE / "yolov8n.pt"
        source = str(weights_path) if weights_path.exists() else "yolov8n.pt"
        self.model = YOLO(source)
        self.conf_threshold = conf_threshold
        self.device = device or "cpu"
        self.imgsz = imgsz

    def count(self, frame_bgr: np.ndarray) -> int:
        results = self.model.predict(
            frame_bgr,
            classes=[0],
            conf=self.conf_threshold,
            imgsz=self.imgsz,
            verbose=False,
            device=self.device,
        )
        boxes = results[0].boxes
        if boxes is None:
            return 0
        return int(len(boxes))


class ViolenceDetector:
    def __init__(
        self,
        weights: str | Path = DEFAULT_WEIGHTS,
        conf_threshold: float = 0.60,
        device: str | None = None,
    ):
        weights = Path(weights)
        if not weights.exists():
            raise FileNotFoundError(f"Model weights not found: {weights}")

        self.model = YOLO(str(weights))
        self.conf_threshold = conf_threshold
        self.device = device or "cpu"
        self.names = dict(self.model.names)  # {0: 'non_violence', 1: 'violence'}
        self.violence_idx = next(
            (i for i, n in self.names.items() if "violence" in n.lower() and "non" not in n.lower()),
            1,
        )

    def predict(self, frame_bgr: np.ndarray) -> ViolenceResult:
        """Classify a single BGR frame. Returns ViolenceResult."""
        # Resize before YOLO so Pi does not copy a 720p tensor every infer.
        h, w = frame_bgr.shape[:2]
        if w != INFER_SIZE or h != INFER_SIZE:
            frame_bgr = cv2.resize(frame_bgr, (INFER_SIZE, INFER_SIZE), interpolation=cv2.INTER_AREA)

        kwargs = {"verbose": False, "imgsz": INFER_SIZE, "device": self.device}
        results = self.model.predict(frame_bgr, **kwargs)
        probs = results[0].probs

        top1 = int(probs.top1)
        top1_conf = float(probs.top1conf)
        raw = probs.data.cpu().numpy()
        scores = {self.names[i]: float(raw[i]) for i in range(len(self.names))}

        violence_name = self.names[self.violence_idx]
        violence_conf = scores.get(violence_name, 0.0)
        # Top-1 gating: violence must be the winning class, not only above threshold.
        is_violence = top1 == self.violence_idx and violence_conf >= self.conf_threshold

        return ViolenceResult(
            label=violence_name if is_violence else self.names[top1],
            confidence=violence_conf if is_violence else top1_conf,
            is_violence=is_violence,
            scores=scores,
        )
