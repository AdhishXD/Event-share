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

gatherly_host="${GATHERLY_HOST:-127.0.0.1}"

echo "Gatherly is starting on ${gatherly_host}:8000"
exec .venv/bin/uvicorn app.main:app --host "$gatherly_host" --port 8000

