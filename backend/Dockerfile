FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
# CPU-only PyTorch keeps the image small (~1.5 GB). For NVIDIA GPUs build with
#   --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu124
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir torch torchvision --index-url ${TORCH_INDEX} \
    && pip install --no-cache-dir -r requirements.txt \
    # ultralytics pulls in GUI OpenCV, which needs X11/GL system libraries; keep only the headless build
    && pip uninstall -y opencv-python \
    && pip install --no-cache-dir --force-reinstall --no-deps "opencv-python-headless>=4.9" \
    && python -c "import cv2, ultralytics; print('cv2', cv2.__version__)"

# Bake the default detector weights into the image (no download on first analysis).
RUN mkdir -p /opt/models && cd /opt/models \
    && YOLO_CONFIG_DIR=/tmp python -c "from ultralytics import YOLO; YOLO('yolo11n.pt')" \
    && ls -la /opt/models

COPY app ./app
ENV TV_DATA_DIR=/data \
    TV_MODEL_PATH=/opt/models/yolo11n.pt \
    YOLO_CONFIG_DIR=/data/ultralytics
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
