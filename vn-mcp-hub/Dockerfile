FROM python:3.13-slim

WORKDIR /app

# System deps for sentence-transformers + scraping
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast pip
RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv pip install --system --no-cache .

COPY src/ ./src/
COPY data/ ./data/

# Pre-warm chroma directory so volume mount works
RUN mkdir -p /app/chroma_db

EXPOSE 8005

CMD ["python", "-m", "src.main"]
