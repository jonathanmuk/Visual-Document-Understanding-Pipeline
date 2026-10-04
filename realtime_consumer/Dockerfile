FROM nvidia/cuda:12.2.2-cudnn8-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System libraries for OpenCV. PDFs are rendered by pypdfium2, which the SDK
# installs itself, so no system PDF tools are needed.
RUN apt-get update && apt-get install -y \
    python3-pip python3-dev \
    libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# The SDK, the layout model's runtime, and the queue libraries. OpenCV is used
# by the layout model's post-processing inside transformers.
RUN pip3 install --no-cache-dir \
    "glmocr[selfhosted,layout]==0.1.4" \
    transformers==5.3.0 \
    redis \
    loguru \
    opencv-python-headless \
    prometheus_client

COPY config.yaml /app/config.yaml
COPY profiles /app/profiles
COPY vdu_queue.py vdu_metrics.py vdu_inspect.py vdu_profiles.py worker.py /app/

# Caches point at /tmp so the root filesystem can be mounted read-only.
ENV GLMOCR_CONFIG_PATH=/app/config.yaml \
    HOME=/tmp \
    HF_HOME=/tmp/hf \
    XDG_CACHE_HOME=/tmp/cache

# An unprivileged user. It writes only to /tmp and /dev/shm.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin vdu
USER 10001

CMD ["python3", "worker.py"]
