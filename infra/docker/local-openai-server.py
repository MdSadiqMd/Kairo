from __future__ import annotations

import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import torch
from fastapi import FastAPI
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response
from transformers import AutoModelForCausalLM, AutoTokenizer


class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[Message]
    max_tokens: int = Field(default=128, ge=1, le=1024)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


model_id = os.environ.get("MODEL_ID", "MODEL_PROVIDER/Model-0.6B")
served_model_name = os.environ.get("SERVED_MODEL_NAME", model_id)
max_model_len = int(os.environ.get("MAX_MODEL_LEN", "4096"))
host = os.environ.get("VLLM_HOST", "0.0.0.0")
port = int(os.environ.get("VLLM_PORT", "8000"))

tokenizer: Any = None
model: Any = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global tokenizer, model
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch.float32,
        device_map="cpu",
        trust_remote_code=True,
    )
    model.eval()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": model_id}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/chat/completions")
def chat_completions(req: ChatCompletionRequest) -> dict[str, Any]:
    prompt_messages = [message.model_dump() for message in req.messages]
    prompt = tokenizer.apply_chat_template(
        prompt_messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        truncation=True,
        max_length=max_model_len,
    )
    with torch.inference_mode():
        generated = model.generate(
            **inputs,
            max_new_tokens=req.max_tokens,
            do_sample=req.temperature > 0,
            temperature=max(req.temperature, 1e-5),
            pad_token_id=tokenizer.eos_token_id,
        )
    output_tokens = generated[0][inputs["input_ids"].shape[-1] :]
    content = tokenizer.decode(output_tokens, skip_special_tokens=True).strip()
    prompt_tokens = int(inputs["input_ids"].shape[-1])
    completion_tokens = int(output_tokens.shape[-1])
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model or served_model_name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=host, port=port, access_log=False)
