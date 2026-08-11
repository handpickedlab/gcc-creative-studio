# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Use a Python image with uv pre-installed
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install the project into `/app`
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Update package lists and install ffmpeg
RUN apt-get update && apt-get install -y ffmpeg

# Headless LibreOffice converts DOCX/PPT/PPTX/ODP research-library uploads to
# PDF. The crosextra fonts are metric-compatible Calibri/Cambria substitutes:
# without them LibreOffice silently swaps fonts and slide layouts reflow.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-core \
    libreoffice-writer \
    libreoffice-impress \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
    fonts-liberation \
    fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

# Reset the entrypoint, don't invoke `uv`
ENTRYPOINT []

# Set default environment variables
ENV ENVIRONMENT="development"
ENV FRONTEND_URL="http://localhost:4200"

EXPOSE 8080

# 2 workers: enough for an internal tool (async workers, concurrency=160) and
# it halves both cold-boot import contention and the memory footprint.
CMD ["gunicorn", "main:app", "--workers=2", "--worker-class=uvicorn.workers.UvicornWorker", "--timeout=36000", "--bind=0.0.0.0:8080"]
