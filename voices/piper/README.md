# Piper Vietnamese voices (ONNX)

Giọng TTS **không** nằm trong Docker image. User tải từ **GitHub Release** của repo này.

| | |
|--|--|
| Release tag | `piper-voices-v1` |
| Engine | Piper 1.3.x |
| Sample rate | 22050 Hz |
| Default | `ngochuyennew` |
| Số giọng | 19 (~60 MB mỗi file `.onnx`) |

## Tải về

Repo **private** → cần đăng nhập GitHub (`gh auth login`) hoặc `GH_TOKEN` / `GITHUB_TOKEN`.

```bash
# Chỉ giọng mặc định (~60 MB)
python scripts/download_piper_voices.py --pack minimal

# Cả 19 giọng (~1.2 GB)
python scripts/download_piper_voices.py --pack full

# Một hoặc vài id
python scripts/download_piper_voices.py --voice ngochuyennew --voice banmai

# Thư mục đích (mặc định: data/piper)
python scripts/download_piper_voices.py --pack minimal --out /data/piper
```

Cần: Python 3.10+, và một trong:

- `gh` CLI đã `gh auth login`, hoặc  
- env `GH_TOKEN` / `GITHUB_TOKEN` (repo scope read)

## Docker volume

```yaml
services:
  c2a:
    volumes:
      - ./data/piper:/data/piper:ro
    environment:
      TTS_MODEL_DIR: /data/piper
      TTS_VOICE: ngochuyennew
```

Host: chạy script tải vào `./data/piper` trước khi `compose up`.

## Danh sách id

Xem `voices.json` → `packs.full` / `voices[].id`.

## Lưu ý

- File `.onnx` / `.onnx.json` **không** commit vào git (xem `.gitignore`).
- Chỉ asset trên Release; push code manifest/script **không** nhúng model vào image build context (không `COPY` data/piper).
- Giọng custom — kiểm tra quyền sử dụng trước khi public repo / chia sẻ rộng.
