# Multi-stage Docker build for ColPali Embedding API

# Stage 1: Base image with Python and CUDA support
FROM nvidia/cuda:12.1-devel-ubuntu22.04 as base

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3.10-dev \
    python3-pip \
    git \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create symlink for python
RUN ln -s /usr/bin/python3.10 /usr/bin/python

# Install uv for fast Python package management
RUN pip install uv

# Stage 2: Dependencies
FROM base as dependencies

# Set working directory
WORKDIR /app

# Copy pyproject.toml first for better caching
COPY pyproject.toml .

# Install Python dependencies using uv
RUN uv pip install --system --no-cache -e .

# Stage 3: Application
FROM dependencies as application

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash colpali
USER colpali
WORKDIR /home/colpali/app

# Copy application code
COPY --chown=colpali:colpali embedding_service.py .

# Create directories for model cache
RUN mkdir -p /home/colpali/.cache/huggingface

# Set environment variables
ENV HF_HOME=/home/colpali/.cache/huggingface
ENV TRANSFORMERS_CACHE=/home/colpali/.cache/huggingface/models
ENV HF_HUB_CACHE=/home/colpali/.cache/huggingface/hub

# Default configuration
ENV COLPALI_HOST=0.0.0.0
ENV COLPALI_PORT=8765
ENV COLPALI_LOG_LEVEL=INFO
ENV COLPALI_DEVICE=auto
ENV COLPALI_BATCH_SIZE_TEXT=8
ENV COLPALI_BATCH_SIZE_IMAGE=4

# Expose port
EXPOSE 8765

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8765/health || exit 1

# Run the application
CMD ["python", "embedding_service.py"]
