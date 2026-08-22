# vLLM serving image.
# Built and pushed to ECR by build-images.yml / build_image.sh. Based on the
# official OpenAI-compatible vLLM image; the entrypoint builds the serve command
# from env (--served-model-name, --tensor-parallel-size, --max-model-len) and
# NEVER enables the dangerous vLLM dev/admin endpoints.
#
# Pin VLLM_VERSION to an immutable tag per environment — never ship :latest.
ARG VLLM_VERSION=v0.6.6
FROM vllm/vllm-openai:${VLLM_VERSION}

# The Rust HF downloader saturates instance bandwidth on the cold
# ~64GB weight pull (3-5x faster). HF_HOME points at the node-local weight cache
# volume mounted by the Deployment.
ENV HF_HUB_ENABLE_HF_TRANSFER=1 \
    HF_HOME=/models-cache \
    VLLM_HOST=0.0.0.0 \
    VLLM_PORT=8000

# hf_transfer must be present for HF_HUB_ENABLE_HF_TRANSFER to take effect.
RUN pip install --no-cache-dir "hf_transfer>=0.1.6"

COPY vllm-entrypoint.sh /usr/local/bin/vllm-entrypoint.sh
RUN chmod +x /usr/local/bin/vllm-entrypoint.sh

EXPOSE 8000

# Override the base image entrypoint so all serving flags come from env, and the
# dev endpoints are never wired in.
ENTRYPOINT ["/usr/local/bin/vllm-entrypoint.sh"]
