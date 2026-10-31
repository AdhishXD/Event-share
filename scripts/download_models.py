from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "models"
MODELS = {
    "face_detection_yunet_2023mar.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for filename, url in MODELS.items():
        destination = MODEL_DIR / filename
        if destination.exists() and destination.stat().st_size > 100_000:
            print(f"Already present: {filename}")
            continue
        print(f"Downloading {filename}...")
        with urlopen(url, timeout=60) as response, destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        print(f"Saved {destination} ({destination.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()

