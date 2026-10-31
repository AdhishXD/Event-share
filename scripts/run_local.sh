#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/uvicorn ]; then
  echo "The project environment is missing. Run: UV_CACHE_DIR=.uv-cache uv sync"
  exit 1
fi

if [ ! -f models/face_detection_yunet_2023mar.onnx ] || [ ! -f models/face_recognition_sface_2021dec.onnx ]; then
  echo "Face models are missing. Run: .venv/bin/python scripts/download_models.py"
  exit 1
fi

echo "Gatherly is starting at http://127.0.0.1:8000"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

