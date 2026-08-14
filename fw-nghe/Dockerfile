FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir faster-whisper fastapi uvicorn python-multipart
COPY app.py /srv/app.py
WORKDIR /srv
ENV HF_HOME=/data
VOLUME /data
EXPOSE 5000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5000"]
