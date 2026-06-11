from __future__ import annotations

import re
import sqlite3
import xml.etree.ElementTree as ET
from html import unescape
from typing import Iterable

from app.repositories.feed_repository import insert_feed
from app.services.feed_service import valid_url


def extract_feeds_from_text(text: str) -> list[tuple[str, str]]:
    text = unescape(text or "")
    feeds: list[tuple[str, str]] = []

    xml_candidates = [text.strip()]
    xml_match = re.search(r"<\?xml[^\n]*\?>.*?</opml>", text, flags=re.I | re.S)
    if xml_match:
        xml_candidates.insert(0, xml_match.group(0).replace("\\\n", "\n"))

    for xml_text in xml_candidates:
        try:
            root = ET.fromstring(xml_text)
            for node in root.iter("outline"):
                url = node.attrib.get("xmlUrl") or node.attrib.get("xmlurl") or node.attrib.get("url")
                if not url:
                    continue
                name = node.attrib.get("text") or node.attrib.get("title") or url
                feeds.append((name.strip(), url.strip()))
            if feeds:
                break
        except Exception:
            continue

    for chunk in re.findall(r"<outline\b[^>]+>", text, flags=re.I):
        url_m = re.search(r"(?:xmlUrl|xmlurl|url)=[\"']([^\"']+)[\"']", chunk, flags=re.I)
        if not url_m:
            continue
        name_m = re.search(r"(?:text|title)=[\"']([^\"']+)[\"']", chunk, flags=re.I)
        url = url_m.group(1).strip()
        name = name_m.group(1).strip() if name_m else url
        feeds.append((name, url))

    for line in text.splitlines():
        urls = re.findall(r"https?://[^\s\"'<>]+", line)
        for url in urls:
            clean_url = url.rstrip('",;)]}\\')
            name = line.replace(url, "").strip(" \t,-—:：|[]【】") or clean_url
            feeds.append((name, clean_url))

    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for name, url in feeds:
        url = url.strip()
        name = re.sub(r"\s+", " ", name.strip()) or url
        if not valid_url(url) or url in seen:
            continue
        seen.add(url)
        unique.append((name, url))
    return unique


def bulk_import_feeds(feeds: Iterable[tuple[str, str]]) -> dict:
    added = 0
    skipped = 0
    errors: list[str] = []
    for name, url in feeds:
        try:
            insert_feed(name.strip() or url, url.strip(), enabled=True)
            added += 1
        except sqlite3.IntegrityError:
            skipped += 1
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return {"added": added, "skipped": skipped, "errors": errors}

