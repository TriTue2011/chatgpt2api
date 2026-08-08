# ============================================================================
# All-in-one image: chatgpt2api + vn-mcp-hub + captcha-solver
# in ONE container. Managed by supervisord (deploy/supervisord.conf).
#   - chatgpt2api  : public FastAPI + Next.js web UI            (:80)
#   - vn-mcp-hub   : 16 MCP servers + RAG, internal             (127.0.0.1:8005)
#   - captcha API  : captcha solver + headful web login, internal (127.0.0.1:8010)
#   - browser stack: Xvfb + Fluxbox + x11vnc + noVNC            (:6080)
# ============================================================================

# ── Stage 1: build the Next.js web UI ──────────────────────────────────────
# Pin major tags; for supply-chain hard-pin, replace with digest after
#   docker buildx imagetools inspect node:22-alpine --format '{{json .Manifest}}'
# USER non-root: deferred — runtime needs root for Xvfb/x11vnc/noVNC + supervisor.
# Prefer least-privilege via security_opt:no-new-privileges (compose) until stack split.
FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS web-build
WORKDIR /app/web
# npm ci, KHÔNG phải bun. Trước đây image build bằng `bun.lock` còn `npm audit`
# đọc `package-lock.json` — hai cây phụ thuộc khác nhau, nên kết quả audit mô
# tả một thứ KHÔNG phải thứ đang chạy. Một lockfile thì audit và image nói về
# cùng một cây.
#
# Đã bỏ luôn cả `npm install -g bun`: node:22-alpine có sẵn npm.
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY VERSION /app/VERSION
COPY web ./
RUN NEXT_PUBLIC_APP_VERSION="$(cat /app/VERSION)" npm run build

# ── Stage 1b: install the embedded Zalo server (Node zca-js) deps ──────────
# Nhúng thẳng server Zalo cá nhân vào image thay vì pull image bên thứ ba.
FROM node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 AS zalo-build
WORKDIR /zalo-server
COPY zalo-server/package.json zalo-server/package-lock.json* ./
# npm ci (không phải npm install): cài ĐÚNG theo package-lock → build tái lập,
# không tự nâng phiên bản lúc build (giảm rủi ro supply-chain — báo cáo 07/08).
RUN npm ci --omit=dev --no-audit --no-fund
COPY zalo-server ./

# ── Stage 2: unified runtime ───────────────────────────────────────────────
FROM python:3.13-slim@sha256:9662417aace5ae7b8e2609cce472b72a8958e134ba372808abe9cc1a0c0125e6 AS app
# NOTE (P1#10): image runs as root for browser/VNC stack. Do NOT switch USER yet
# without splitting captcha/noVNC into a separate privileged sidecar.
# Pin digests on next rebuild when free build quota returns:
#   docker pull python:3.13-slim && docker image inspect --format='{{index .RepoDigests 0}}'

# Node.js runtime (chạy zalo-server nhúng). Copy nguyên bản cài đặt Node từ image
# node:22 — python:3.13-slim và node:22 cùng nền Debian bookworm nên ABI khớp.
COPY --from=node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DISPLAY=:99 \
    MOZ_DISABLE_CONTENT_SANDBOX=1 \
    MOZ_DISABLE_GMP_SANDBOX=1 \
    CAPTCHA_SOLVER_DISPLAY=:99 \
    CAPTCHA_SOLVER_DATA_DIR=/app/data/captcha \
    ACCOUNTS_DB=/app/data/captcha/accounts.db \
    CHATGPT2API_URL=http://127.0.0.1:80 \
    CAPTCHA_SOLVER_NOVNC_EXTERNAL_URL=http://localhost:6080/vnc.html?host=localhost&port=6080&autoconnect=1 \
    MCP_HUB_INTERNAL_URL=http://127.0.0.1:8005

WORKDIR /app

# System deps merged from all three services:
#  - chatgpt2api : git, libpq-dev, gcc, openssl, libcurl, libnss3, wget, cloudflared
#  - vn-mcp-hub  : tesseract-ocr(+vie), poppler-utils
#  - captcha     : Xvfb, x11vnc, supervisor, fluxbox, novnc, websockify, chromium libs, fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
        git libpq-dev gcc g++ build-essential ca-certificates openssl \
        libcurl4-openssl-dev wget curl gnupg \
        tesseract-ocr tesseract-ocr-vie poppler-utils \
        ffmpeg \
        xvfb x11vnc supervisor fluxbox novnc websockify \
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
        libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
        libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
        libatspi2.0-0 libxshmfence1 fonts-noto-cjk fonts-liberation \
        fonts-noto-color-emoji fonts-freefont-ttf fonts-unifont \
    && rm -rf /var/lib/apt/lists/*

# Piper TTS — CHỈ binary (~25 MB), KHÔNG kèm giọng .onnx. Giọng nằm ngoài image
# trên volume data/piper (tải bằng scripts/download_piper_voices.py) để image
# không phình thêm ~1.2 GB. Bản binary chỉ có amd64/arm64.
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
      amd64) PP="piper_linux_x86_64.tar.gz"; PP_SHA="a50cb45f355b7af1f6d758c1b360717877ba0a398cc8cbe6d2a7a3a26e225992" ;; \
      arm64) PP="piper_linux_aarch64.tar.gz"; PP_SHA="fea0fd2d87c54dbc7078d0f878289f404bd4d6eea6e7444a77835d1537ab88eb" ;; \
      *) PP="" ;; \
    esac && \
    if [ -n "$PP" ]; then \
      wget -q "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/${PP}" -O /tmp/piper.tgz && \
      echo "${PP_SHA}  /tmp/piper.tgz" | sha256sum -c - && \
      mkdir -p /opt && tar -xzf /tmp/piper.tgz -C /opt && rm /tmp/piper.tgz && \
      ln -sf /opt/piper/piper /usr/local/bin/piper ; \
    else echo "piper: bo qua kien truc $ARCH" ; fi

# rclone — cầu nối tới 150+ dịch vụ lưu trữ (Google Drive, OneDrive, Dropbox,
# S3/R2, WebDAV, SFTP…). Một binary Go tĩnh, không kéo thư viện nào theo, nên
# dùng gói .deb sẵn có là đủ — khỏi thêm unzip vào image.
# GHIM PHIÊN BẢN: trước đây dùng `rclone-current-linux-*.deb` — một URL DI
# ĐỘNG, nên mỗi lần build có thể ra một binary khác mà không ai biết, và không
# có checksum nào kiểm được. Checksum dưới đây lấy từ SHA256SUMS thượng nguồn.
ARG RCLONE_VERSION=v1.75.0
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
      amd64) RC_SHA="266598b5c66a42b821571332013cc85a88ffcff8939cf0643861c8d033dd3a4a" ;; \
      arm64) RC_SHA="081c605cbf47ade3114e78db2130766a23281a12b79cdd5774b11dad6c6c0931" ;; \
      *) RC_SHA="" ;; \
    esac && \
    if [ -n "$RC_SHA" ]; then \
      RC="rclone-${RCLONE_VERSION}-linux-${ARCH}.deb" && \
      wget -q "https://downloads.rclone.org/${RCLONE_VERSION}/${RC}" -O /tmp/rclone.deb && \
      echo "${RC_SHA}  /tmp/rclone.deb" | sha256sum -c - && \
      dpkg -i /tmp/rclone.deb && rm /tmp/rclone.deb && rclone version | head -1 ; \
    else echo "rclone: bo qua kien truc $ARCH" ; fi

# cloudflared (Cloudflare Tunnel, used by chatgpt2api)
#
# GHIM PHIÊN BẢN: trước đây dùng `/releases/latest/download/` — mỗi lần build
# lấy bản mới nhất TẠI THỜI ĐIỂM ĐÓ, nên hai lần build cùng một commit có thể
# ra hai image khác nhau, và một bản thượng nguồn hỏng sẽ vào thẳng production
# mà không qua bước xem xét nào.
ARG CLOUDFLARED_VERSION=2026.7.3
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
      amd64) CF_SHA="049777d30f9bf93da6df8bbe31383460eb2aa51a832c6551824d56f9fcc55974" ;; \
      arm64) CF_SHA="d3ea7d22dd337b465da33d6bc1c4b3cfd381407447a2a7d29542c19783430db3" ;; \
      *) echo "unsupported: $ARCH"; exit 1 ;; \
    esac && \
    wget -q "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-${ARCH}.deb" -O /tmp/cf.deb && \
    echo "${CF_SHA}  /tmp/cf.deb" | sha256sum -c - && \
    dpkg -i /tmp/cf.deb && rm /tmp/cf.deb

# OfficeCLI binary (Word/Excel/PPT) — agent tools office_* gọi TRỰC TIẾP
# in-process qua services/officecli.py (không qua MCP hub).
# Pin version for reproducible builds; bump when upgrading intentionally.
# glibc builds for Debian slim (not alpine musl).
ARG OFFICECLI_VERSION=v1.0.140
RUN ARCH=$(dpkg --print-architecture) && \
    case "$ARCH" in \
      amd64) OC="officecli-linux-x64"; OC_SHA="cee68cc2108074e5ae5ad114e1cd5cab4514da8ead4983d5d94aa0acba4f41e8" ;; \
      arm64) OC="officecli-linux-arm64"; OC_SHA="924dd58f57891d1b3fe8cf77f06990f58f8f0c0ddf6fe22e1d91c7f10d3e7576" ;; \
      *) OC="" ;; \
    esac && \
    if [ -n "$OC" ]; then \
      wget -q "https://github.com/iOfficeAI/OfficeCLI/releases/download/${OFFICECLI_VERSION}/${OC}" \
        -O /usr/local/bin/officecli && \
      echo "${OC_SHA}  /usr/local/bin/officecli" | sha256sum -c - && \
      chmod +x /usr/local/bin/officecli && \
      /usr/local/bin/officecli --version || echo "officecli: binary installed (version check optional)" ; \
    else echo "officecli: skip unsupported arch $ARCH" ; fi
ENV OFFICECLI_BIN=/usr/local/bin/officecli \
    OFFICECLI_WORKSPACE=/app/data/office \
    OFFICECLI_SKIP_UPDATE=1

# Chrome/Chromium — Patchright stealth prefers genuine Chrome, but Google
# Chrome ships amd64 ONLY. On arm64 install Debian's chromium instead (the
# solver's _detect_chrome_major + launch fall back to it). TARGETARCH is
# provided automatically by buildx for the target platform.
ARG TARGETARCH
RUN if [ "$TARGETARCH" = "amd64" ]; then \
        wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
        && echo "deb [signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
        && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable ; \
    else \
        apt-get update && apt-get install -y --no-install-recommends chromium ; \
    fi \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps ─────────────────────────────────────────────────────────────
RUN pip install --no-cache-dir uv

# pyproject ghim mirror aliyun (default=true — nhanh ở VN, hay TIMEOUT trên GH
# runner: đã fail vnstock rồi posthog). CI truyền build-arg ép PyPI chính hãng;
# build tay ở VN không truyền gì → vẫn aliyun như cũ.
ARG UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple
ENV UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX}

# chatgpt2api locked deps (reproducible) → /app/.venv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# vn-mcp-hub + captcha-solver + proxy deps on top of the same venv
COPY deploy/extra-requirements.txt /tmp/extra-requirements.txt
RUN uv pip install --python /app/.venv/bin/python -r /tmp/extra-requirements.txt

# VieNeu-TTS: --no-deps để không kéo gradio/pandas (~300MB, chỉ cần cho web UI
# riêng của họ). Dep runtime thật (sea-g2p, tokenizers…) nằm trong
# extra-requirements.txt ở trên. Model KHÔNG trong image — tải về volume
# data/hf bằng scripts/download_vieneu_model.py (engine đọc qua HF_HOME).
RUN uv pip install --python /app/.venv/bin/python --no-deps vieneu
ENV HF_HOME=/app/data/hf

# ── GPU (build-arg GPU=1 → tag :gpu, amd64) ────────────────────────────────
# Torch CUDA (~6GB cài đặt) để VieNeu tự chuyển engine PyTorch khi thấy GPU
# (voice.tts.vieneu_backend mặc định "auto"). transformers ghim theo README
# VieNeu — bản ổn định nhất cho SDK GPU. Image thường (GPU=0) không cài gì.
# Host cần driver NVIDIA + nvidia-container-toolkit + compose `gpus: all`.
ARG GPU=0
RUN if [ "$GPU" = "1" ]; then \
      uv pip install --python /app/.venv/bin/python \
        "torch==2.8.0" "torchaudio==2.8.0" \
        --index-url https://download.pytorch.org/whl/cu128 && \
      uv pip install --python /app/.venv/bin/python "transformers==4.57.6" ; \
    fi

# sherpa-onnx (STT) nạp thư viện native qua dlopen("libonnxruntime.so") nhưng
# gói onnxruntime chỉ có file libonnxruntime.so.<version> → loader không thấy.
# Symlink đúng tên + đăng ký qua ldconfig (bền hơn LD_LIBRARY_PATH, áp dụng cả
# cho supervisord). PHẢI đặt SAU khi onnxruntime đã cài (nó không nằm trong
# uv.lock mà đến từ extra-requirements).
RUN ORT_DIR=$(find /app/.venv -type d -path '*/onnxruntime/capi' | head -1) && \
    SO=$(find "$ORT_DIR" -name 'libonnxruntime.so.*' 2>/dev/null | head -1) && \
    if [ -n "$SO" ]; then \
        ln -sf "$SO" "$ORT_DIR/libonnxruntime.so" && \
        echo "$ORT_DIR" > /etc/ld.so.conf.d/onnxruntime.conf && ldconfig && \
        echo "onnxruntime symlink OK: $SO" ; \
    else echo "WARN: khong tim thay libonnxruntime.so.* (STT se loi)" ; fi

# Browsers for the captcha-solver (patchright Chromium + Firefox + cloakbrowser)
RUN /app/.venv/bin/patchright install chromium \
    && /app/.venv/bin/patchright install firefox \
    && /app/.venv/bin/python -m cloakbrowser install

# ── Application code ────────────────────────────────────────────────────────
# chatgpt2api at /app
COPY main.py VERSION ./
RUN echo '{}' > config.json
COPY api ./api
COPY services ./services
COPY utils ./utils
COPY scripts ./scripts
COPY voices ./voices
COPY --from=web-build /app/web/out ./web_dist

# vn-mcp-hub at /app/mcp_hub (keeps its own `src` package)
COPY vn-mcp-hub/src ./mcp_hub/src
COPY vn-mcp-hub/data ./mcp_hub/data

# captcha-solver at /app/captcha
COPY captcha-solver/src ./captcha/src

# zalo-server (Node zca-js) nhúng tại /app/zalo-server, kèm node_modules đã cài.
COPY --from=zalo-build /zalo-server /app/zalo-server

# Data layout: single bind mount at /app/data. vn-mcp-hub hardcodes /app/chroma_db
# → symlink it into the mount so everything persists under one host directory.
# zalo-server: users.json dùng cwd/data, cookies/sessions/messages dùng
# DATA_DIRECTORY → symlink data về /app/data/zalo_bot để mọi thứ persist chung.
RUN mkdir -p /app/data && ln -sf /app/data/chroma_db /app/chroma_db \
    && rm -rf /app/zalo-server/data \
    && ln -sf /app/data/zalo_bot /app/zalo-server/data
# rm -rf TRƯỚC khi symlink: COPY ở trên mang theo cả /app/zalo-server/data (gồm
# cookies/users.json nhúng trong image). `ln -sf` vào một THƯ MỤC ĐÃ TỒN TẠI chỉ
# tạo link BÊN TRONG nó, không thay thế → image dùng users.json admin/admin nhúng
# sẵn và data không persist (báo cáo bảo mật 07/08). Xoá dir trước rồi mới link.

COPY deploy/supervisord.conf /etc/supervisor/conf.d/c2a.conf

EXPOSE 80 6080 3001

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=30s \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:80/version')" || exit 1

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/c2a.conf"]
