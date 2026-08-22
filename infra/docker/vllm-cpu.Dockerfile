FROM vllm/vllm-openai-cpu:latest-arm64

ENV VLLM_HOST=0.0.0.0 \
    VLLM_PORT=8000 \
    VLLM_DEVICE=cpu \
    MODEL_ID=Qwen/Qwen2.5-0.5B-Instruct \
    SERVED_MODEL_NAME=reasoner \
    MAX_MODEL_LEN=2048 \
    VLLM_DTYPE=float16 \
    VLLM_CPU_KVCACHE_SPACE=1 \
    VLLM_CPU_OMP_THREADS_BIND=0-1 \
    VLLM_CPU_NUM_OF_RESERVED_CPU=1 \
    MAX_NUM_SEQS=1 \
    MAX_NUM_BATCHED_TOKENS=512 \
    HF_HOME=/models-cache \
    HF_HUB_ENABLE_HF_TRANSFER=1

RUN mkdir -p /models-cache

COPY vllm-entrypoint.sh /usr/local/bin/vllm-entrypoint.sh
RUN chmod +x /usr/local/bin/vllm-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/vllm-entrypoint.sh"]
