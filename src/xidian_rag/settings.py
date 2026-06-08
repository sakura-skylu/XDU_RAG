from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .models import SourceConfig


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "sources.json"
DATA_DIR = PROJECT_ROOT / "data"
KNOWLEDGE_BASE_DIR = DATA_DIR / "knowledge_base"
RAW_PAGES_DIR = KNOWLEDGE_BASE_DIR / "pages"
DOCUMENTS_PATH = DATA_DIR / "documents.jsonl"
CHUNKS_PATH = DATA_DIR / "chunks.jsonl"
INDEX_PATH = DATA_DIR / "index" / "local_vectors.json"
CHROMA_DIR = DATA_DIR / "index" / "chroma"
FAILURES_PATH = DATA_DIR / "crawl_failures.jsonl"


def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    return int(value)


@dataclass(slots=True)
class Settings:
    openai_api_key: str | None
    openai_base_url: str
    openai_chat_model: str
    openai_embedding_model: str
    openai_embedding_api_key: str | None
    openai_embedding_base_url: str
    openai_embedding_dimensions: int | None
    use_api_embeddings: bool
    use_api_chat: bool
    use_direct_api_chat: bool
    vector_store: str
    request_timeout_seconds: float
    crawl_delay_seconds: float


def load_settings() -> Settings:
    _load_dotenv()
    openai_api_key = os.getenv("OPENAI_API_KEY") or None
    openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    embedding_base_url = os.getenv("OPENAI_EMBEDDING_BASE_URL", openai_base_url).rstrip("/")
    embedding_api_key = os.getenv("OPENAI_EMBEDDING_API_KEY") or os.getenv("ZHIPU_API_KEY") or None
    if embedding_api_key is None and embedding_base_url == openai_base_url:
        embedding_api_key = openai_api_key

    return Settings(
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        openai_chat_model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
        openai_embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        openai_embedding_api_key=embedding_api_key,
        openai_embedding_base_url=embedding_base_url,
        openai_embedding_dimensions=env_int("OPENAI_EMBEDDING_DIMENSIONS"),
        use_api_embeddings=env_bool("USE_API_EMBEDDINGS", False),
        use_api_chat=env_bool("USE_API_CHAT", False),
        use_direct_api_chat=env_bool("USE_DIRECT_API_CHAT", False),
        vector_store=os.getenv("VECTOR_STORE", "local").lower(),
        request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "12")),
        crawl_delay_seconds=float(os.getenv("CRAWL_DELAY_SECONDS", "0.6")),
    )


def load_sources() -> tuple[list[str], list[SourceConfig], dict[str, list[str]]]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    domains = config["allowed_domains"]
    sources = [SourceConfig(**item) for item in config["seed_urls"]]
    category_keywords = config["category_keywords"]
    return domains, sources, category_keywords
