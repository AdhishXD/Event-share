from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("GATHERLY_DATA_DIR", ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
REFERENCE_DIR = DATA_DIR / "references"
DATABASE_PATH = DATA_DIR / "gatherly.sqlite3"
MODEL_DIR = Path(os.getenv("GATHERLY_MODEL_DIR", ROOT / "models"))
DETECTOR_MODEL = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
RECOGNIZER_MODEL = MODEL_DIR / "face_recognition_sface_2021dec.onnx"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
AUTO_MATCH_THRESHOLD = float(os.getenv("GATHERLY_AUTO_THRESHOLD", "0.48"))
REVIEW_MATCH_THRESHOLD = float(os.getenv("GATHERLY_REVIEW_THRESHOLD", "0.36"))


def ensure_directories() -> None:
    for directory in (DATA_DIR, UPLOAD_DIR, REFERENCE_DIR, MODEL_DIR):
        directory.mkdir(parents=True, exist_ok=True)

