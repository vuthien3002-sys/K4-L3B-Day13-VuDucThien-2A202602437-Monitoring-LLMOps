from __future__ import annotations

import time

from .incidents import STATE
from .pii import summarize_text
from .tracing import get_langfuse_client, observe

CORPUS = {
    "refund": ["Refunds are available within 7 days with proof of purchase."],
    "monitoring": ["Metrics detect incidents, logs identify affected requests, traces localize the root cause."],
    "policy": ["Do not expose PII in logs. Use sanitized summaries only."],
}
FALLBACK_DOCS = ["No domain document matched. Use general fallback answer."]


# Không capture input/output thô vì câu hỏi có thể chứa PII; chỉ ghi preview đã scrub
@observe(name="retrieval", as_type="retriever", capture_input=False, capture_output=False)
def retrieve(message: str) -> list[str]:
    client = get_langfuse_client()
    client.update_current_span(input={"query_preview": summarize_text(message)})
    if STATE["tool_fail"]:
        raise RuntimeError("Vector store timeout")
    if STATE["rag_slow"]:
        time.sleep(2.5)
    lowered = message.lower()
    matched_key = next((key for key in CORPUS if key in lowered), None)
    docs = CORPUS[matched_key] if matched_key else FALLBACK_DOCS
    client.update_current_span(
        output={"doc_count": len(docs)},
        metadata={"matched_key": matched_key or "fallback", "doc_count": len(docs)},
    )
    return docs
