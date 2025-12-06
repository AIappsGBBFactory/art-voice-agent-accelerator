# Note: build this image from the root of the project directory

# Use an official Python runtime as a parent image
FROM python:3.11-slim-bookworm AS builder

# Install uv - extremely fast Python package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required for audio processing
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc build-essential portaudio19-dev && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies first (better layer caching)
# Only copy files needed for dependency resolution
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=README.md,target=README.md \
    --mount=type=bind,source=LICENSE,target=LICENSE \
    uv sync --frozen --no-install-project --no-editable

# Copy source code
COPY ./apps /app/apps
COPY ./src /app/src
COPY ./utils /app/utils
COPY pyproject.toml README.md LICENSE ./

# Install the project itself
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-editable

# =============================================================================
# Final production image
# =============================================================================
FROM python:3.11-slim-bookworm

# Update packages to mitigate vulnerabilities
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends portaudio19-dev && \
    rm -rf /var/lib/apt/lists/*

# Create a non-root user and group
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Copy application code
COPY --chown=appuser:appuser ./apps /app/apps
COPY --chown=appuser:appuser ./src /app/src
COPY --chown=appuser:appuser ./utils /app/utils

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app:$PYTHONPATH"

# Switch to the non-root user
USER appuser

# Expose the port the app runs on
EXPOSE 8000

# Define the command to run the application
CMD ["uvicorn", "apps.artagent.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]