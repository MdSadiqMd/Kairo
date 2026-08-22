FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY libs/ libs/
COPY ml/ ml/

RUN uv pip install --system -e libs/kairo_common -e "ml[aws]"

USER 1000

CMD ["python", "-m", "kairo_ml.proofs.worker"]
