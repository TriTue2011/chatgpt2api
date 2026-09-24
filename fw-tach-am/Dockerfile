FROM beveradb/audio-separator:gpu-0.44.5@sha256:bd230b1beae492ac14b1ced27dc7e7b9de5e7c4bd1ebdef9e96b36fca7d26087
USER root
RUN python3 -m pip install --no-cache-dir "fastapi==0.136.0" "uvicorn==0.44.0"
# ONNX của c2a (nhận mặt, Kokoro Việt — mục /onnx trong app.py) chạy CUDA qua
# onnxruntime-gpu 1.23, bản này cần CUDA 12 + cuDNN 9 cho CUDA 12; image gốc
# chỉ có thư viện CUDA 13 của torch (đo 24/09/2026: "libcublasLt.so.12: cannot
# open shared object file" → ORT lặng lẽ chạy CPU). Cài vào thư mục RIÊNG vì
# nvidia-cudnn-cu12 ghi cùng tên libcudnn.so.9 với bản CUDA 13 của torch; gom
# .so về một chỗ cho onnxruntime.preload_dlls(directory=...). Chủ máy duyệt sửa
# Dockerfile này 24/09/2026.
RUN python3 -m pip install --no-cache-dir --target /opt/cu12 \
      "nvidia-cuda-runtime-cu12==12.*" "nvidia-cublas-cu12==12.*" \
      "nvidia-cufft-cu12==11.*" "nvidia-curand-cu12==10.*" \
      "nvidia-cuda-nvrtc-cu12==12.*" "nvidia-cudnn-cu12==9.*" \
 && mkdir -p /opt/cu12/lib \
 && ln -s /opt/cu12/nvidia/*/lib/*.so* /opt/cu12/lib/
COPY app.py /srv/app.py
WORKDIR /srv
ENV HF_HOME=/data/huggingface
VOLUME /data
EXPOSE 5000
ENTRYPOINT []
CMD ["python3", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5000"]
