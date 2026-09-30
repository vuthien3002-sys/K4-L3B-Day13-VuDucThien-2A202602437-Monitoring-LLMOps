from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from .incidents import STATE
from .pii import summarize_text
from .tracing import get_langfuse_client, observe

# USD cho mỗi 1 triệu token
INPUT_PRICE_PER_MTOK = 3.0
OUTPUT_PRICE_PER_MTOK = 15.0


def estimate_cost(tokens_in: int, tokens_out: int) -> dict[str, float]:
    input_cost = (tokens_in / 1_000_000) * INPUT_PRICE_PER_MTOK
    output_cost = (tokens_out / 1_000_000) * OUTPUT_PRICE_PER_MTOK
    return {
        "input": round(input_cost, 6),
        "output": round(output_cost, 6),
        "total": round(input_cost + output_cost, 6),
    }


@dataclass
class FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class FakeResponse:
    text: str
    usage: FakeUsage
    model: str
    ttft_ms: int


class FakeLLM:
    def __init__(self, model: str = "claude-sonnet-4-5") -> None:
        self.model = model

    # Prompt đã điền câu hỏi có thể chứa PII nên không capture; prompt version được
    # nối vào generation qua propagate_attributes(prompt=...) ở agent
    @observe(name="generation", as_type="generation", capture_input=False, capture_output=False)
    def generate(self, prompt: str) -> FakeResponse:
        started = time.perf_counter()
        time.sleep(0.05)  # mô phỏng thời điểm token đầu tiên sẵn sàng
        ttft_ms = int((time.perf_counter() - started) * 1000)
        first_token_at = datetime.now(timezone.utc)
        time.sleep(0.10)
        input_tokens = max(20, len(prompt) // 4)
        output_tokens = random.randint(80, 180)
        if STATE["cost_spike"]:
            output_tokens *= 4
        answer = (
            "Starter answer. You should improve this output logic and add better quality checks. "
            "Use retrieved context and keep responses concise."
        )
        get_langfuse_client().update_current_generation(
            model=self.model,
            completion_start_time=first_token_at,
            usage_details={"input": input_tokens, "output": output_tokens},
            cost_details=estimate_cost(input_tokens, output_tokens),
            output={"answer_preview": summarize_text(answer)},
            metadata={"ttft_ms": ttft_ms, "prompt_chars": len(prompt)},
        )
        return FakeResponse(
            text=answer,
            usage=FakeUsage(input_tokens, output_tokens),
            model=self.model,
            ttft_ms=ttft_ms,
        )
