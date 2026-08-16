FROM beveradb/audio-separator:gpu-0.44.5@sha256:bd230b1beae492ac14b1ced27dc7e7b9de5e7c4bd1ebdef9e96b36fca7d26087
USER root
RUN python3 -m pip install --no-cache-dir "fastapi==0.136.0" "uvicorn==0.44.0"
COPY app.py /srv/app.py
WORKDIR /srv
ENV HF_HOME=/data/huggingface
VOLUME /data
EXPOSE 5000
ENTRYPOINT []
CMD ["python3", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5000"]
