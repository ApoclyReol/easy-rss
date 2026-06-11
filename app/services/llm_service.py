from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.relevance import RelevanceItem, item_from_record, parse_relevance_response
from app.services.settings_service import LLMSettings


@dataclass
class LLMPreviewResult:
    item_id: int
    title: str
    relevant: bool | None = None
    error: str | None = None


@dataclass
class APITestResult:
    ok: bool
    connection_message: str
    auth_message: str
    model_message: str
    raw_response_preview: str = ""


def _normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def render_prompt(settings: LLMSettings, item: RelevanceItem) -> str:
    return settings.prompt_template.format(
        user_interest=settings.user_interest.strip(),
        title=item.title.strip(),
        authors=item.authors.strip(),
        journal=item.journal.strip(),
        summary=item.summary.strip(),
        content=item.content.strip(),
        url=item.url.strip(),
    )


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


def run_llm_preview(items: list[dict], settings: LLMSettings) -> list[LLMPreviewResult]:
    results: list[LLMPreviewResult] = []
    for item in items:
        try:
            relevance_item = item_from_record(item)
            prompt = render_prompt(settings, relevance_item)
            content, _ = _post_chat_completion(settings, prompt)
            relevant = parse_relevance_response(content)
            results.append(
                LLMPreviewResult(
                    item_id=int(item["id"]),
                    title=str(item.get("title") or ""),
                    relevant=relevant,
                )
            )
        except Exception as exc:
            results.append(
                LLMPreviewResult(
                    item_id=int(item["id"]),
                    title=str(item.get("title") or ""),
                    error=str(exc),
                )
            )
    return results

