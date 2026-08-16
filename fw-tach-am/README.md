# fw-tach-am

API GPU dùng source separation để ước lượng track `Instrumental` trước khi lồng
TTS. Track âm thanh gốc không được mux vào đầu ra. Đây không phải phép tách
lossless: cảnh có lời chồng nhạc/hiệu ứng có thể còn rò giọng; giọng hát thuộc
nhạc cũng có thể bị làm mờ.

Image kế thừa `beveradb/audio-separator:gpu-0.44.5`, chạy mặc định
`UVR-MDX-NET-Inst_HQ_3.onnx` vì nhẹ hơn BS-Roformer trên RTX 2060 Super 8 GB.
Tệp dài được chia thành khúc 300 giây để chặn đỉnh RAM/VRAM. Model tải lần đầu
vào `/data/models` và được dùng lại ở lượt sau.

```bash
docker build -t fw-tach-am .
TOKEN='thay-bang-chuoi-ngau-nhien-dai'
docker run -d --rm --name fw-tach-am --gpus all -p 5004:5000 \
  -v fw-tach-am-data:/data \
  -e SEPARATOR_API_TOKEN="$TOKEN" fw-tach-am
curl -H "X-API-Key: $TOKEN" http://127.0.0.1:5004/health
curl --request POST --upload-file soundtrack.wav \
  -H "X-API-Key: $TOKEN" -H 'X-Job-Token: thu-nghiem-12345678' \
  -H 'X-Filename: soundtrack.wav' -H 'Content-Type: audio/wav' \
  'http://127.0.0.1:5004/tach-nen?stem=nen' -o background.wav
```

Mỗi request gọi model trong subprocess. Khi xong subprocess thoát nên VRAM
được nhả trước khi gateway cho Whisper/Qwen/máy dịch nhận hàng tiếp theo.
API bắt buộc có khóa dùng chung; lệnh `/unload` còn kiểm mã sở hữu nên một
request bị từ chối hoặc client khác trong LAN không thể dừng nhầm job đang chạy.
Body được đọc streaming và chặn theo `SEPARATOR_MAX_UPLOAD_BYTES`, không spool
trọn request nhiều GB trước khi kiểm giới hạn.
