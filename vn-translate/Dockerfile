# vn-translate — máy dịch tự chủ (NLLB-200 + thuật ngữ chuyên ngành)
# API giống LibreTranslate. KHÔNG chứa model: tải về volume /data lần chạy đầu
# (~600 MB), các lần sau đọc từ đĩa — cùng nếp LibreTranslate.
FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Chạy không root (uid cố định để chủ máy chown volume /data nếu bind mount).
COPY entrypoint.sh /entrypoint.sh
RUN useradd --system --uid 1033 vntranslate && mkdir -p /data && chown 1033:1033 /data && chmod +x /entrypoint.sh
VOLUME /data
EXPOSE 5000

# HOME + HF_HOME trỏ vào /data: bộ tải Xet của huggingface_hub ghi cache vào
# ~/.cache — user hệ thống KHÔNG có home, thiếu hai biến này là Permission
# denied ngay lúc tải model (đo thật 12/08).
ENV TT_MODEL_DIR=/data/models TT_GLOSSARY_DIR=/data/glossary HOME=/data HF_HOME=/data/hf
# Entrypoint chown /data rồi TỰ hạ quyền — không cần init container ngoài.
ENTRYPOINT ["/entrypoint.sh"]
