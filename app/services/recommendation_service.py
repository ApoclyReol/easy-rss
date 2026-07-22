from __future__ import annotations

import hashlib
import math
import re
import uuid
from dataclasses import dataclass

import jieba
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from app.repositories.recommendation_repository import (
    get_keyword_overrides,
    list_training_items,
    list_unread_items,
    record_model_error,
    replace_model_results,
)

POSITIVE_STATUSES = frozenset({"interested", "archived"})
NEGATIVE_STATUSES = frozenset({"hidden", "expired"})
MIN_CLASS_SAMPLES = 2

STOPWORDS = frozenset(
    """
    a an and are as at be been by can could for from has have how in into is it its may might
    more most new not of on or our paper research study than that the their these this through to
    toward using via was we were what when where which while who with would results method analysis
    based effects evidence approach role model models data among between implications introduction
    一种 一个 以及 通过 对于 关于 中的 研究 分析 基于 影响 作用 方法 模型 数据 结果 视角 机制
    """.split()
)
TOKEN_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{1,}|[\u4e00-\u9fff]+")


@dataclass(frozen=True)
class RecommendationRun:
    model_version: str
    positive_count: int
    negative_count: int
    unread_count: int
    high_count: int
    pending_count: int
    low_count: int
    unscored_count: int


def tokenize_text(text: str) -> list[str]:
    tokens: list[str] = []
    for part in TOKEN_PATTERN.findall((text or "").casefold()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            candidates = jieba.lcut(part, cut_all=False)
        else:
            candidates = [part.replace("_", "-")]
        for candidate in candidates:
            normalized = candidate.strip().casefold()
            if len(normalized) < 2 or normalized in STOPWORDS or normalized.isdigit():
                continue
            tokens.append(normalized)
    return tokens


def build_document(item: dict) -> str:
    title = str(item.get("title") or "").strip()
    summary = str(item.get("summary") or "").strip()
    return " ".join(part for part in (title, title, summary) if part)


def content_hash(item: dict) -> str:
    return hashlib.sha256(build_document(item).encode("utf-8")).hexdigest()


def score_to_tier(score: float) -> str:
    if score >= 70:
        return "high"
    if score <= 30:
        return "low"
    return "pending"


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def _manual_logit_adjustment(text: str, overrides: dict[str, dict]) -> float:
    normalized = text.casefold()
    adjustment = 0.0
    for keyword, override in overrides.items():
        if override.get("is_disabled") or keyword not in normalized:
            continue
        manual_weight = override.get("manual_weight")
        if manual_weight is not None:
            adjustment += float(manual_weight)
    return adjustment


def rebuild_keyword_recommendations() -> RecommendationRun:
    training_items = list_training_items()
    unread_items = list_unread_items()
    positive_count = sum(item["item_status"] in POSITIVE_STATUSES for item in training_items)
    negative_count = sum(item["item_status"] in NEGATIVE_STATUSES for item in training_items)
    model_version = uuid.uuid4().hex

    if positive_count < MIN_CLASS_SAMPLES or negative_count < MIN_CLASS_SAMPLES:
        error = f"训练样本不足：正样本至少 {MIN_CLASS_SAMPLES} 篇，负样本至少 {MIN_CLASS_SAMPLES} 篇"
        record_model_error(
            model_version=model_version,
            positive_count=positive_count,
            negative_count=negative_count,
            unread_count=len(unread_items),
            error=error,
        )
        raise ValueError(error)

    overrides = get_keyword_overrides()
    disabled = {keyword for keyword, row in overrides.items() if row.get("is_disabled")}

    def tokenizer(text: str) -> list[str]:
        return [token for token in tokenize_text(text) if token not in disabled]

    documents = [build_document(item) for item in training_items]
    labels = np.asarray([1 if item["item_status"] in POSITIVE_STATUSES else 0 for item in training_items])
    vectorizer = TfidfVectorizer(
        tokenizer=tokenizer,
        token_pattern=None,
        lowercase=False,
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.98,
        max_features=5000,
        sublinear_tf=True,
    )
    try:
        matrix = vectorizer.fit_transform(documents)
        classifier = LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            random_state=0,
        )
        classifier.fit(matrix, labels)
    except ValueError as exc:
        error = f"关键词模型无法训练：{exc}"
        record_model_error(
            model_version=model_version,
            positive_count=positive_count,
            negative_count=negative_count,
            unread_count=len(unread_items),
            error=error,
        )
        raise ValueError(error) from exc

    feature_names = vectorizer.get_feature_names_out()
    coefficients = classifier.coef_[0]
    for index, feature_name in enumerate(feature_names):
        if str(feature_name) in disabled:
            coefficients[index] = 0.0
    presence = matrix.copy()
    presence.data = np.ones_like(presence.data)
    positive_presence = np.asarray(presence[labels == 1].sum(axis=0)).ravel()
    negative_presence = np.asarray(presence[labels == 0].sum(axis=0)).ravel()
    keywords = [
        {
            "keyword": str(feature_names[index]),
            "auto_weight": float(coefficients[index]),
            "positive_count": int(positive_presence[index]),
            "negative_count": int(negative_presence[index]),
        }
        for index in range(len(feature_names))
    ]

    scores: list[dict] = []
    if unread_items:
        unread_documents = [build_document(item) for item in unread_items]
        usable_indexes = [index for index, document in enumerate(unread_documents) if tokenize_text(document)]
        if usable_indexes:
            usable_documents = [unread_documents[index] for index in usable_indexes]
            unread_matrix = vectorizer.transform(usable_documents)
            # Center an item with no learned keyword evidence at 50. The fitted
            # intercept reflects the very uneven history size and would otherwise
            # turn mere absence of positive terms into a confident negative.
            evidence_logits = np.asarray(unread_matrix @ coefficients).ravel() * 2.0
            for row_index, item_index in enumerate(usable_indexes):
                item = unread_items[item_index]
                document = unread_documents[item_index]
                logit = float(evidence_logits[row_index]) + _manual_logit_adjustment(document, overrides)
                score = round(_sigmoid(logit) * 100, 1)
                contributions = unread_matrix.getrow(row_index).multiply(coefficients).tocoo()
                ranked = sorted(
                    (
                        (str(feature_names[col]), float(value))
                        for col, value in zip(contributions.col, contributions.data)
                        if abs(float(value)) > 0
                    ),
                    key=lambda pair: abs(pair[1]),
                    reverse=True,
                )
                manual_matches = [
                    (keyword, float(override.get("manual_weight") or 0))
                    for keyword, override in overrides.items()
                    if not override.get("is_disabled") and override.get("manual_weight") is not None
                    and keyword in document.casefold()
                ]
                matched = [
                    {"keyword": keyword, "weight": round(weight, 4)}
                    for keyword, weight in (manual_matches + ranked)[:6]
                ]
                scores.append(
                    {
                        "item_id": int(item["id"]),
                        "keyword_score": score,
                        "keyword_tier": score_to_tier(score),
                        "matched_keywords": matched,
                        "content_hash": content_hash(item),
                    }
                )

    replace_model_results(
        model_version=model_version,
        positive_count=positive_count,
        negative_count=negative_count,
        unread_count=len(unread_items),
        keywords=keywords,
        scores=scores,
    )
    counts = {"high": 0, "pending": 0, "low": 0}
    for row in scores:
        counts[row["keyword_tier"]] += 1
    return RecommendationRun(
        model_version=model_version,
        positive_count=positive_count,
        negative_count=negative_count,
        unread_count=len(unread_items),
        high_count=counts["high"],
        pending_count=counts["pending"],
        low_count=counts["low"],
        unscored_count=len(unread_items) - len(scores),
    )
