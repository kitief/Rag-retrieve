FROM python:3.11-slim

WORKDIR /app

# PyPI index. Defaults to the Tsinghua mirror because the upstream
# files.pythonhosted.org endpoint is unreliable on some networks; override at
# build time for a strict-upstream build:
#   docker compose build --build-arg PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# NOTE: tesseract-ocr and ffmpeg are intentionally NOT installed.
# Image OCR and audio/video transcription are shelved for now (see
# .env: ENABLE_OCR_UPLOADS / ENABLE_AUDIO_VIDEO_UPLOADS). To bring them back:
#   1. uncomment the apt-get block below
#   2. uncomment pytesseract / faster-whisper in requirements.txt
#   3. set the two ENABLE_* flags to true
#
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     tesseract-ocr \
#     ffmpeg \
#     && rm -rf /var/lib/apt/lists/*

# Copy requirements and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=120 --retries 5 -r requirements.txt


# Copy application code
COPY . .

# Ensure entrypoint script has LF line endings and is executable
RUN sed -i 's/\r$//' docker-entrypoint.sh && chmod +x docker-entrypoint.sh

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

CMD ["/bin/sh", "/app/docker-entrypoint.sh"]
