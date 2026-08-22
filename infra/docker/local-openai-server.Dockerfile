FROM python:3.11-slim-bookworm

ENV VLLM_HOST=0.0.0.0 \
    VLLM_PORT=8000 \
    MODEL_ID=MODEL_PROVIDER/Model-4B \
    SERVED_MODEL_NAME=model-32b \
    MAX_MODEL_LEN=4096 \
    HF_HOME=/models-cache

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir "transformers>=4.51.0" fastapi "uvicorn[standard]" prometheus-client \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /models-cache

COPY local-openai-server.py /usr/local/bin/local-openai-server.py

EXPOSE 8000
CMD ["python", "/usr/local/bin/local-openai-server.py"]
