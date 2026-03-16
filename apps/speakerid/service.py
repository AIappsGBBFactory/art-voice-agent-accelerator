"""
Speaker ID Service — SpeechBrain ECAPA-TDNN speaker verification.

Stateless microservice that extracts 192-dim speaker embeddings from audio
and compares them via cosine similarity.  No database, no Azure dependency.
"""

from __future__ import annotations

import base64
import io
import logging
from contextlib import asynccontextmanager

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, Field

logger = logging.getLogger("speakerid")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ── Globals ──────────────────────────────────────────────────────────────────

_model = None
_ready = False
MODEL_SOURCE = "/app/models/ecapa-src"
MODEL_SAVEDIR = "/app/models/spkrec-ecapa-voxceleb"


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model, _ready
    logger.info("Loading ECAPA-TDNN model from %s …", MODEL_SOURCE)
    from speechbrain.inference.speaker import EncoderClassifier

    _model = EncoderClassifier.from_hparams(
        source=MODEL_SOURCE,
        savedir=MODEL_SAVEDIR,
        run_opts={"device": "cpu"},
    )
    _ready = True
    logger.info("Model loaded — ready to serve requests")
    yield
    logger.info("Shutting down")


app = FastAPI(title="Speaker ID Service", lifespan=lifespan)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_audio(wav_bytes: bytes) -> torch.Tensor:
    """Load WAV bytes into a torch tensor (mono, 16 kHz)."""
    buf = io.BytesIO(wav_bytes)
    data, sr = sf.read(buf, dtype="float32")
    # data shape: (samples,) for mono, (samples, channels) for stereo
    if data.ndim == 2:
        data = data.mean(axis=1)
    # Resample to 16 kHz if needed
    if sr != 16000:
        import torchaudio
        waveform = torch.from_numpy(data).unsqueeze(0)
        waveform = torchaudio.functional.resample(waveform, sr, 16000)
        return waveform
    return torch.from_numpy(data).unsqueeze(0)


def _extract_embedding(wav_bytes: bytes) -> list[float]:
    """Extract a 192-dim speaker embedding from WAV audio."""
    waveform = _load_audio(wav_bytes)
    with torch.no_grad():
        embedding = _model.encode_batch(waveform)
    # embedding shape: [1, 1, 192] → flatten to list
    vec = embedding.squeeze().cpu().numpy()
    # L2-normalize for consistent cosine similarity
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two unit vectors (just dot product)."""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    # Re-normalize in case stored embeddings weren't normalized
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na > 0:
        va = va / na
    if nb > 0:
        vb = vb / nb
    return float(np.dot(va, vb))


# ── Request / Response models ────────────────────────────────────────────────

class EmbeddingResponse(BaseModel):
    embedding: list[float]


class VerifyRequest(BaseModel):
    audio: str = Field(..., description="Base64-encoded WAV audio")
    embedding: list[float] = Field(..., description="Stored speaker embedding")
    threshold: float = Field(default=0.40, description="Cosine similarity threshold")


class VerifyResponse(BaseModel):
    match: bool
    score: float
    threshold: float


class HealthResponse(BaseModel):
    status: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    return {"status": "healthy"}


@app.get("/ready", response_model=HealthResponse)
async def ready():
    if not _ready:
        return Response(content='{"status":"loading"}', status_code=503, media_type="application/json")
    return {"status": "ready"}


@app.post("/embed", response_model=EmbeddingResponse)
async def embed(request: Request):
    """Extract speaker embedding from WAV audio."""
    wav_bytes = await request.body()
    if not wav_bytes:
        return Response(content='{"error":"empty body"}', status_code=400, media_type="application/json")
    embedding = _extract_embedding(wav_bytes)
    logger.info("Extracted embedding (%d dims) from %d bytes", len(embedding), len(wav_bytes))
    return {"embedding": embedding}


@app.post("/enroll", response_model=EmbeddingResponse)
async def enroll(request: Request):
    """Enroll a speaker — extract and return their embedding for storage."""
    wav_bytes = await request.body()
    if not wav_bytes:
        return Response(content='{"error":"empty body"}', status_code=400, media_type="application/json")
    embedding = _extract_embedding(wav_bytes)
    logger.info("Enrollment embedding (%d dims) from %d bytes", len(embedding), len(wav_bytes))
    return {"embedding": embedding}


@app.post("/verify", response_model=VerifyResponse)
async def verify(req: VerifyRequest):
    """Verify audio against a stored embedding."""
    wav_bytes = base64.b64decode(req.audio)
    new_embedding = _extract_embedding(wav_bytes)
    score = _cosine_similarity(new_embedding, req.embedding)
    match = score >= req.threshold
    logger.info("Verification: score=%.3f threshold=%.2f match=%s", score, req.threshold, match)
    return {"match": match, "score": score, "threshold": req.threshold}
