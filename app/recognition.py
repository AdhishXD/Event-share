import json
from pathlib import Path
from threading import Lock

import cv2
import numpy as np

from .config import DETECTOR_MODEL, RECOGNIZER_MODEL


class ModelsUnavailable(RuntimeError):
    pass


class FaceRecognition:
    def __init__(self) -> None:
        self._detector = None
        self._recognizer = None
        self._lock = Lock()

    def _load(self):
        if not DETECTOR_MODEL.exists() or not RECOGNIZER_MODEL.exists():
            raise ModelsUnavailable(
                "Recognition models are missing. Run: uv run python scripts/download_models.py"
            )
        if self._detector is None:
            self._detector = cv2.FaceDetectorYN.create(
                str(DETECTOR_MODEL), "", (320, 320), 0.8, 0.3, 5000
            )
            self._recognizer = cv2.FaceRecognizerSF.create(str(RECOGNIZER_MODEL), "")
        return self._detector, self._recognizer

    @staticmethod
    def decode_image(path: Path) -> np.ndarray:
        raw = np.fromfile(path, dtype=np.uint8)
        image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("The uploaded file is not a readable image.")
        return image

    def embeddings(self, path: Path) -> list[np.ndarray]:
        with self._lock:
            detector, recognizer = self._load()
            image = self.decode_image(path)
            height, width = image.shape[:2]
            detector.setInputSize((width, height))
            _, faces = detector.detect(image)
            if faces is None:
                return []
            output = []
            for face in faces:
                # Ignore tiny background faces that are unlikely to be meaningful subjects.
                if (float(face[2]) * float(face[3])) / (width * height) < 0.0015:
                    continue
                aligned = recognizer.alignCrop(image, face)
                feature = recognizer.feature(aligned).flatten().astype(np.float32)
                norm = np.linalg.norm(feature)
                if norm:
                    output.append(feature / norm)
            return output

    @staticmethod
    def average(features: list[np.ndarray]) -> np.ndarray:
        feature = np.mean(np.stack(features), axis=0)
        return feature / np.linalg.norm(feature)

    @staticmethod
    def similarity(left: np.ndarray, right: np.ndarray) -> float:
        return float(np.dot(left, right))


recognition = FaceRecognition()


def serialize_embedding(feature: np.ndarray) -> str:
    return json.dumps(feature.tolist(), separators=(",", ":"))


def deserialize_embedding(value: str) -> np.ndarray:
    return np.asarray(json.loads(value), dtype=np.float32)

