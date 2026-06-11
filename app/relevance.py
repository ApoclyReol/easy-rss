from __future__ import annotations

from dataclasses import dataclass

from app.config import DEFAULT_PROMPT_TEMPLATE

TRUE_OUTPUT = "true"
FALSE_OUTPUT = "false"
ALLOWED_OUTPUTS = frozenset({TRUE_OUTPUT, FALSE_OUTPUT})


@dataclass(frozen=True)
class RelevanceItem:
    """RSS item context used for LLM relevance classification."""

    title: str
    summary: str = ""
    content: str = ""
    url: str = ""
    authors: str = ""
    journal: str = ""


def build_relevance_prompt(item: RelevanceItem, user_interest: str) -> str:
    """Build a prompt that forces a boolean-only relevance answer."""

    return DEFAULT_PROMPT_TEMPLATE.format(
        user_interest=user_interest.strip(),
        title=item.title.strip(),
        authors=item.authors.strip(),
        journal=item.journal.strip(),
        summary=item.summary.strip(),
        content=item.content.strip(),
        url=item.url.strip(),
    )


def item_from_record(record: dict) -> RelevanceItem:
    """Create relevance input from an item row/dict used by the reader app."""

    return RelevanceItem(
        title=str(record.get("title") or ""),
        summary=str(record.get("summary") or ""),
        url=str(record.get("link") or record.get("url") or ""),
        authors=str(record.get("authors") or ""),
        journal=str(record.get("journal") or ""),
    )


def parse_relevance_response(response_text: str) -> bool:
    """Parse a strict true/false LLM relevance response."""

    normalized = response_text.strip().lower()
    if normalized == TRUE_OUTPUT:
        return True
    if normalized == FALSE_OUTPUT:
        return False

    raise ValueError(
        'Invalid relevance response. Expected exactly "true" or "false" with no extra text.'
    )
