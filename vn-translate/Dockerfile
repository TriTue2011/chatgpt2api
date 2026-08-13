# vn-translate — máy dịch tự chủ (EnViT5 cho anh↔việt, NLLB-200 cho phần còn
# lại, + thuật ngữ chuyên ngành). API giống LibreTranslate.
#
# EnViT5 được NHÚNG SẴN vào image (~265 MB): nó là đường chính cho cặp dùng
# nhiều nhất nên không được phụ thuộc mạng lúc khởi động, mà cũng KHÔNG có bản
# CTranslate2 nào công khai trên Hugging Face để tải về (đã tra 13/08) — phải
# tự chuyển đổi. Việc chuyển cần torch (~800 MB) nên làm ở tầng riêng rồi vứt
# đi, image chạy thật vẫn không có torch.
#
# NLLB thì vẫn tải về volume /data lần chạy đầu (~600 MB) như cũ: nó chỉ dùng
# cho nhật/hàn/trung, tải sẵn vào image là bắt mọi người gánh 600 MB cho phần
# ít dùng.
FROM python:3.12-slim AS chuyen_doi
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir "transformers>=4.44,<5" ctranslate2 sentencepiece protobuf
ARG ENVIT5=VietAI/envit5-translation
RUN ct2-transformers-converter --model "$ENVIT5" --output_dir /envit5 --quantization int8 \
 && python -c "from transformers import AutoTokenizer; \
AutoTokenizer.from_pretrained('$ENVIT5').save_pretrained('/envit5')"

FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=chuyen_doi /envit5 /opt/envit5
COPY app ./app

# Chạy không root (uid cố định để chủ máy chown volume /data nếu bind mount).
COPY entrypoint.sh /entrypoint.sh
RUN useradd --system --uid 1033 vntranslate && mkdir -p /data && chown 1033:1033 /data && chmod +x /entrypoint.sh
VOLUME /data
EXPOSE 5000

# HOME + HF_HOME trỏ vào /data: bộ tải Xet của huggingface_hub ghi cache vào
# ~/.cache — user hệ thống KHÔNG có home, thiếu hai biến này là Permission
# denied ngay lúc tải model (đo thật 12/08).
ENV TT_MODEL_DIR=/data/models TT_GLOSSARY_DIR=/data/glossary HOME=/data HF_HOME=/data/hf \
    TT_ENVIT5_DIR=/opt/envit5
# Entrypoint chown /data rồi TỰ hạ quyền — không cần init container ngoài.
ENTRYPOINT ["/entrypoint.sh"]
