FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libsndfile1 ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Install all Python deps together for correct resolution
# PyTorch CPU-only pinned for speechbrain 1.0.x compatibility
COPY apps/speakerid/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir \
    torch==2.5.1+cpu torchaudio==2.5.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Pre-download ECAPA-TDNN model at build time (avoids runtime download)
# Download to a cache dir, then load from it to verify
RUN python -c "\
from huggingface_hub import snapshot_download; \
snapshot_download('speechbrain/spkrec-ecapa-voxceleb', local_dir='/app/models/ecapa-src'); \
from speechbrain.inference.speaker import EncoderClassifier; \
EncoderClassifier.from_hparams( \
    source='/app/models/ecapa-src', \
    savedir='/app/models/spkrec-ecapa-voxceleb', \
    run_opts={'device': 'cpu'} \
)"

# ── Runtime stage ────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages and model from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/models /app/models

# Copy service code
COPY apps/speakerid/service.py /app/service.py

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8000"]
