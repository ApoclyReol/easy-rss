from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
YEAR_RE = re.compile(r"(?:19|20)\d{2}")
SUMMARY_FIELD_PATTERNS = {
    "publication_date": [
        re.compile(r"Publication\s+date[:：]\s*(.+?)(?=\s+(?:Source|Author\(s\)|Authors?)[:：]|$)", re.I),
    ],
    "source": [
        re.compile(r"Source[:：]\s*(.+?)(?=\s+(?:Publication\s+date|Author\(s\)|Authors?)[:：]|$)", re.I),
    ],
    "authors": [
        re.compile(r"Author\(s\)[:：]\s*(.+?)(?=\s+(?:Publication\s+date|Source|Authors?)[:：]|$)", re.I),
        re.compile(r"Authors?[:：]\s*(.+?)(?=\s+(?:Publication\s+date|Source)[:：]|$)", re.I),
    ],
}
DATE_TEXT_RE = re.compile(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b|\b[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}\b|\b\d{4}-\d{2}-\d{2}\b")


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)


def first_nonempty_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
            if text:
                return value
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    text = (item.get("value") or item.get("content") or "").strip()
                    if text:
                        return text
                elif isinstance(item, str) and item.strip():
                    return item
        elif isinstance(value, dict):
            text = (value.get("value") or value.get("content") or "").strip()
            if text:
                return text
    return ""


def extract_entry_summary(entry: dict[str, Any]) -> str:
    return first_nonempty_text(
        entry.get("summary"),
        entry.get("description"),
        entry.get("content"),
        entry.get("content_encoded"),
        entry.get("summary_detail"),
        entry.get("subtitle"),
    )


def parse_loose_date_text(value: str | None) -> str:
    if not value:
        return ""
    text = strip_html(value)
    match = DATE_TEXT_RE.search(text)
    if not match:
        return ""
    candidate = match.group(0)
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(candidate, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def extract_summary_metadata(summary: str | None) -> dict[str, str]:
    text = strip_html(summary)
    meta = {"publication_date": "", "source": "", "authors": ""}
    if not text:
        return meta
    for field, patterns in SUMMARY_FIELD_PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                meta[field] = match.group(1).strip()
                break
    return meta


def clean_summary_text(summary: str | None) -> str:
    text = strip_html(summary)
    if not text:
        return ""
    cleaned = text
    for patterns in SUMMARY_FIELD_PATTERNS.values():
        for pattern in patterns:
            cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" |;-")
    return cleaned


def normalize_journal_name(value: str | None) -> str:
    text = strip_html(value)
    if not text:
        return ""
    prefixes = [
        "ScienceDirect Publication:",
    ]
    for prefix in prefixes:
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[\u3000\s\-—–_·,，.。:：;；!！?？'‘’\"“”()（）\[\]【】{}《》<>/\\|]+", "", text)
    return text


def canonicalize_link(link: str | None) -> str:
    if not link:
        return ""
    parts = urlsplit(link.strip())
    host = (parts.netloc or "").lower()
    if host.endswith("cnki.net"):
        # CNKI 文献详情依赖 query 参数定位具体文章，不能像其他站点那样直接去掉。
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
    # 某些 RSS 链接常带一次性参数；去掉 query/fragment，避免链接变化影响判断
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def find_doi(*values: str | None) -> str:
    joined = " ".join(v or "" for v in values)
    m = DOI_RE.search(joined)
    return m.group(0).rstrip(".,;)").lower() if m else ""


def infer_year(*values: str | None) -> str:
    for v in values:
        if not v:
            continue
        m = YEAR_RE.search(v)
        if m:
            return m.group(0)
    return ""


def parse_pub_date(entry: dict[str, Any]) -> str:
    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
            return dt.isoformat()
        except Exception:
            parsed = parse_loose_date_text(str(raw))
            return parsed or str(raw)
    meta = extract_summary_metadata(entry.get("summary") or entry.get("description"))
    fallback = meta.get("publication_date", "")
    return parse_loose_date_text(fallback) or fallback


def extract_authors(summary: str, entry: dict[str, Any]) -> str:
    if entry.get("authors"):
        names = []
        for a in entry.get("authors") or []:
            name = a.get("name") if isinstance(a, dict) else str(a)
            if name:
                names.append(name)
        return "; ".join(names)

    # 尽量兼容中文 RSS 摘要中的“作者/Author”字段
    meta = extract_summary_metadata(summary)
    if meta["authors"]:
        return meta["authors"]
    for pat in [r"作者[:：]\s*([^。；;\n]+)", r"Author[s]?[:：]\s*([^。；;\n]+)"]:
        m = re.search(pat, summary, re.I)
        if m:
            return m.group(1).strip()
    return ""


def stable_guid(title: str, journal: str, year: str, authors: str, doi: str) -> tuple[str, str]:
    title_norm = normalize_text(title)
    if doi:
        return f"doi:{doi}", title_norm

    author_key = normalize_text(authors)[:48]
    if author_key:
        # 正式文献尽量摆脱可编辑的期刊名，让改订阅名不会改文章身份。
        base = "|".join([title_norm, year or "", author_key])
    else:
        # 低信息条目（如 Editorial Board）没有作者时，仍保留期刊名参与身份，避免跨期刊误并。
        base = "|".join([title_norm, year or "", normalize_text(journal)])
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]
    return f"cnki-local:{digest}", title_norm


def entry_to_item(entry: dict[str, Any], feed_name: str) -> dict[str, str]:
    title = strip_html(entry.get("title")) or "Untitled"
    raw_summary = extract_entry_summary(entry)
    summary = clean_summary_text(raw_summary)
    link = canonicalize_link(entry.get("link"))
    pub_date = parse_pub_date(entry)
    doi = find_doi(title, summary, link)
    year = infer_year(pub_date, summary, title)
    authors = extract_authors(strip_html(raw_summary), entry)
    meta = extract_summary_metadata(raw_summary)
    journal = (
        normalize_journal_name(feed_name)
        or normalize_journal_name(meta.get("source"))
        or strip_html(entry.get("source", {}).get("title") if isinstance(entry.get("source"), dict) else "")
    )
    guid, title_norm = stable_guid(title, journal, year, authors, doi)
    return {
        "stable_guid": guid,
        "title": title,
        "title_norm": title_norm,
        "authors": authors,
        "journal": journal,
        "year": year,
        "doi": doi,
        "link": link,
        "pub_date": pub_date,
        "summary": summary,
    }
