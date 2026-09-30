from __future__ import annotations

from app import mock_llm, mock_rag


class RecordingClient:
    def __init__(self) -> None:
        self.span_updates: list[dict] = []
        self.generation_updates: list[dict] = []

    def update_current_span(self, **kwargs) -> None:
        self.span_updates.append(kwargs)

    def update_current_generation(self, **kwargs) -> None:
        self.generation_updates.append(kwargs)


def test_retrieve_and_generate_are_child_observations() -> None:
    # @observe bọc hàm gốc; __wrapped__ chỉ tồn tại khi decorator đã được áp dụng
    assert hasattr(mock_rag.retrieve, "__wrapped__")
    assert hasattr(mock_llm.FakeLLM.generate, "__wrapped__")


def test_generation_reports_model_usage_and_cost(monkeypatch) -> None:
    client = RecordingClient()
    monkeypatch.setattr(mock_llm, "get_langfuse_client", lambda: client)

    llm = mock_llm.FakeLLM(model="claude-sonnet-4-5")
    response = mock_llm.FakeLLM.generate.__wrapped__(llm, "Feature=qa\nDocs=x\nQuestion=hi")

    update = client.generation_updates[-1]
    assert update["model"] == "claude-sonnet-4-5"
    assert update["usage_details"] == {
        "input": response.usage.input_tokens,
        "output": response.usage.output_tokens,
    }
    expected = mock_llm.estimate_cost(response.usage.input_tokens, response.usage.output_tokens)
    assert update["cost_details"] == expected
    assert update["cost_details"]["total"] > 0
    assert update["completion_start_time"] is not None


def test_retrieval_span_does_not_capture_raw_pii(monkeypatch) -> None:
    client = RecordingClient()
    monkeypatch.setattr(mock_rag, "get_langfuse_client", lambda: client)

    docs = mock_rag.retrieve.__wrapped__("policy question from student@vinuni.edu.vn 0987654321")

    recorded = repr(client.span_updates)
    assert docs == mock_rag.CORPUS["policy"]
    assert "student@vinuni.edu.vn" not in recorded
    assert "0987654321" not in recorded
    assert client.span_updates[-1]["metadata"] == {"matched_key": "policy", "doc_count": 1}


def test_estimate_cost_matches_token_pricing() -> None:
    cost = mock_llm.estimate_cost(1_000_000, 1_000_000)
    assert cost == {"input": 3.0, "output": 15.0, "total": 18.0}
