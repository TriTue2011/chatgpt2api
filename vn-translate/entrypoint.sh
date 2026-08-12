#!/bin/sh
# Chạy bằng root ĐÚNG MỘT VIỆC: đổi chủ /data (volume mới do Docker tạo thuộc
# root, tiến trình 1033 không ghi được — đúng lỗi LibreTranslate gặp, đo thật
# 12/08). Xong hạ quyền xuống vntranslate rồi exec server. `su` hạ quyền xuôi
# nên vẫn chạy dưới no-new-privileges.
set -e
mkdir -p /data/models /data/glossary
chown -R vntranslate:vntranslate /data
exec su -s /bin/sh vntranslate -c 'exec python -m uvicorn app.main:app --host 0.0.0.0 --port 5000'
