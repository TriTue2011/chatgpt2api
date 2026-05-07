# Stage 1: Build Web
FROM node:22-alpine AS web-build
WORKDIR /app/web
RUN apk add --no-cache git
RUN git clone https://github.com/TriTue2011/chatgpt2api.git /app_source
WORKDIR /app_source/web
RUN npm install
RUN npm run build

# Stage 2: App
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libpq-dev \
    gcc \
    openssl \
    jq \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

# Clone the source code
RUN git clone https://github.com/TriTue2011/chatgpt2api.git .

# Copy web build from stage 1
COPY --from=web-build /app_source/web/out ./web_dist

# Sync dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Add the addon run script (copied from the build context)
COPY run.sh ./
RUN chmod +x ./run.sh

EXPOSE 80

CMD ["/app/run.sh"]
