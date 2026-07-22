from __future__ import annotations

LLM_REVIEW_OUTPUTS = frozenset({"high", "low"})


def parse_llm_review_response(response_text: str) -> str:
    normalized = response_text.strip().lower()
    if normalized in LLM_REVIEW_OUTPUTS:
        return normalized
    raise ValueError('Invalid recommendation response. Expected exactly "high" or "low".')
