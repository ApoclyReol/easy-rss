from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.relevance import parse_llm_review_response
from app.repositories.recommendation_repository import list_keywords, list_pending_for_llm, save_llm_review
from app.services.settings_service import LLMSettings


@dataclass
class APITestResult:
    ok: bool
    connection_message: str
    auth_message: str
    model_message: str
    raw_response_preview: str = ""


@dataclass
class LLMReviewRun:
    total: int
    high: int
    low: int
    failed: int


def _normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def _post_chat_completion(settings: LLMSettings, prompt: str) -> tuple[str, dict]:
    if not settings.base_url.strip():
        raise ValueError("请先填写 base_url")
    if not settings.api_key.strip():
        raise ValueError("请先填写 api_key")
    if not settings.model.strip():
        raise ValueError("请先填写 model")

    url = _normalize_base_url(settings.base_url)
    with httpx.Client(timeout=45) as client:
        response = client.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.api_key.strip()}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.model.strip(),
                "temperature": 0,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            },
        )
        response.raise_for_status()
        data = response.json()

    choices = data.get("choices") or []
    if not choices:
        raise ValueError("LLM 响应中没有 choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        content = "".join(text_parts)
    if not isinstance(content, str):
        raise ValueError("LLM 响应中没有可解析的文本内容")
    return content, data


def test_llm_settings(settings: LLMSettings) -> APITestResult:
    try:
        content, _ = _post_chat_completion(
            settings,
            "Reply with exactly true. Do not return any other text.",
        )
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        auth_ok = status_code not in {401, 403}
        model_ok = status_code not in {404, 422}
        return APITestResult(
            ok=False,
            connection_message="已连接到接口，但请求失败",
            auth_message="认证失败" if not auth_ok else "认证已通过",
            model_message="模型不可用或接口不接受该模型" if not model_ok else "模型参数已送达接口",
            raw_response_preview=exc.response.text[:300],
        )
    except Exception as exc:
        return APITestResult(
            ok=False,
            connection_message=f"连接失败：{exc}",
            auth_message="未完成认证验证",
            model_message="未完成模型验证",
        )

    normalized = content.strip()
    return APITestResult(
        ok=True,
        connection_message="连接成功",
        auth_message="认证通过",
        model_message="模型可调用",
        raw_response_preview=normalized[:300],
    )


def _render_review_prompt(item: dict, interest_keywords: list[dict]) -> str:
    positive = [row["keyword"] for row in interest_keywords if float(row.get("effective_weight") or 0) > 0][:20]
    negative = [row["keyword"] for row in interest_keywords if float(row.get("effective_weight") or 0) < 0][:20]
    matched = str(item.get("matched_keywords") or "[]")
    return f"""You are reviewing a borderline academic-paper recommendation for one researcher.

Return exactly one lowercase token:
- high: the paper is sufficiently relevant to prioritize
- low: the paper is sufficiently irrelevant to deprioritize

Do not return JSON, reasons, or any other text.

Research interest description:
{item.get('user_interest', '')}

Learned positive keywords:
{', '.join(positive)}

Learned negative keywords:
{', '.join(negative)}

Keyword model score:
{item.get('keyword_score')}

Matched keyword evidence:
{matched}

Title:
{item.get('title') or ''}

Abstract:
{item.get('summary') or ''}
"""


def run_pending_llm_review(settings: LLMSettings) -> LLMReviewRun:
    items = list_pending_for_llm()
    keywords = list_keywords(limit=100)
    high = low = failed = 0
    for item in items:
        try:
            item["user_interest"] = settings.user_interest
            response, _ = _post_chat_completion(settings, _render_review_prompt(item, keywords))
            tier = parse_llm_review_response(response)
            save_llm_review(int(item["id"]), tier=tier, error=None)
            if tier == "high":
                high += 1
            else:
                low += 1
        except Exception as exc:
            save_llm_review(int(item["id"]), tier=None, error=str(exc)[:500])
            failed += 1
    return LLMReviewRun(total=len(items), high=high, low=low, failed=failed)
