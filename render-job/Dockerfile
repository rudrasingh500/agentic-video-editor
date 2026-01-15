# Video Render Job Container
# 
# Two variants:
# 1. CPU-only (Dockerfile) - Uses libx264/libx265 for software encoding
# 2. GPU-enabled (Dockerfile.gpu) - Uses NVIDIA NVENC for hardware acceleration
#
# Build CPU version:
#   docker build -t video-render-cpu .
#
# Build GPU version:
#   docker build -f Dockerfile.gpu -t video-render-gpu .

FROM python:3.11-slim

# Install FFmpeg and dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libavcodec-extra \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY *.py .

# Create directories for GCS mounts
RUN mkdir -p /inputs /outputs /tmp/render

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV RENDER_TEMP_DIR=/tmp/render

# Entry point
ENTRYPOINT ["python", "entrypoint.py"]
