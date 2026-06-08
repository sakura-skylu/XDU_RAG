from __future__ import annotations

import hashlib
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urldefrag, urljoin, urlparse

from .categorizer import categorize
from .content_filter import is_navigation_index_page
from .io import append_jsonl, ensure_parent
from .models import Document, SourceConfig
from .settings import FAILURES_PATH, RAW_PAGES_DIR, Settings

TEXT_MIN_LENGTH = 120
SKIP_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".css",
    ".js",
    ".zip",
    ".rar",
    ".7z",
    ".mp4",
    ".mp3",
    ".avi",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".pdf",
}


def normalize_url(url: str) -> str:
    url, _fragment = urldefrag(url)
    return url.rstrip("/")


def is_allowed_url(url: str, allowed_domains: Iterable[str]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    path = parsed.path.lower()
    if any(path.endswith(extension) for extension in SKIP_EXTENSIONS):
        return False
    host = parsed.netloc.lower()
    return any(host == domain or host.endswith("." + domain) for domain in allowed_domains)


def extract_publish_date(text: str) -> str | None:
    patterns = [
        r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})",
        r"发布时间[:：]\s*(20\d{2}-\d{1,2}-\d{1,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            if len(match.groups()) == 3:
                year, month, day = match.groups()
                return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
            return match.group(1)
    return None


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(版权所有|Copyright).*", "", text, flags=re.IGNORECASE)
    return text.strip()


def make_doc_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def raw_page_path(url: str) -> Path:
    return RAW_PAGES_DIR / f"{make_doc_id(url)}.html"


def save_raw_page_snapshot(url: str, content: bytes) -> None:
    path = raw_page_path(url)
    ensure_parent(path)
    path.write_bytes(content)


def parse_html_page(html: str | bytes, base_url: str) -> tuple[str, str, list[str]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()

    title = soup.title.get_text(" ", strip=True) if soup.title else base_url
    candidates = soup.select("article, .article, .content, .main, .v_news_content, #vsb_content, #content")
    if candidates:
        body = max(candidates, key=lambda node: len(node.get_text(" ", strip=True))).get_text(" ", strip=True)
    else:
        body = soup.get_text(" ", strip=True)

    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        links.append(urljoin(base_url, anchor["href"]))
    return title, clean_text(body), links


def fetch_page(url: str, settings: Settings) -> tuple[str, str, list[str]]:
    import requests

    response = requests.get(
        url,
        headers={"User-Agent": "XidianRAGBot/0.1 (+student course project)"},
        timeout=settings.request_timeout_seconds,
    )
    response.raise_for_status()
    save_raw_page_snapshot(url, response.content)
    response.encoding = response.apparent_encoding or response.encoding
    return parse_html_page(response.text, url)


def make_document(
    url: str,
    title: str,
    content: str,
    source: SourceConfig,
    category_keywords: dict[str, list[str]],
) -> Document:
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    doc_id = make_doc_id(url)
    category = categorize(f"{title} {content[:1000]}", source.category, category_keywords)
    return Document(
        doc_id=doc_id,
        title=title,
        url=url,
        source_site=source.source_site,
        category=category,
        publish_date=extract_publish_date(content),
        content=content,
        crawl_time=datetime.now(timezone.utc).isoformat(),
        checksum=checksum,
    )


class WebCrawler:
    def __init__(
        self,
        allowed_domains: list[str],
        sources: list[SourceConfig],
        category_keywords: dict[str, list[str]],
        settings: Settings,
    ) -> None:
        self.allowed_domains = allowed_domains
        self.sources = sources
        self.category_keywords = category_keywords
        self.settings = settings

    def crawl(self, max_pages: int = 200, max_depth: int = 2) -> list[Document]:
        documents: list[Document] = []
        seen_urls: set[str] = set()
        seen_checksums: set[str] = set()
        queue: deque[tuple[str, SourceConfig, int]] = deque(
            (source.url, source, 0) for source in self.sources
        )

        while queue and len(documents) < max_pages:
            url, source, depth = queue.popleft()
            normalized = normalize_url(url)
            if normalized in seen_urls or not is_allowed_url(normalized, self.allowed_domains):
                continue
            seen_urls.add(normalized)
            try:
                title, content, links = fetch_page(normalized, self.settings)
                if len(content) >= TEXT_MIN_LENGTH and not is_navigation_index_page(title, content, normalized):
                    document = make_document(normalized, title, content, source, self.category_keywords)
                    if document.checksum not in seen_checksums:
                        documents.append(document)
                        seen_checksums.add(document.checksum)
                if depth < max_depth:
                    for link in links:
                        normalized_link = normalize_url(link)
                        if normalized_link not in seen_urls and is_allowed_url(normalized_link, self.allowed_domains):
                            queue.append((normalized_link, source, depth + 1))
                time.sleep(self.settings.crawl_delay_seconds)
            except Exception as exc:
                append_jsonl(
                    FAILURES_PATH,
                    {
                        "url": normalized,
                        "source_site": source.source_site,
                        "may_require_vpn": source.may_require_vpn,
                        "error": str(exc),
                        "time": datetime.now(timezone.utc).isoformat(),
                    },
                )
        return documents
