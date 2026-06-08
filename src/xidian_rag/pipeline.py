from __future__ import annotations

from pathlib import Path

from .chunking import make_chunks
from .content_filter import is_navigation_index_page
from .crawler import TEXT_MIN_LENGTH, WebCrawler, clean_text, make_document, parse_html_page
from .embeddings import build_embedding_provider
from .io import read_jsonl, write_jsonl
from .models import Chunk, Document, SourceConfig
from .settings import CHUNKS_PATH, DOCUMENTS_PATH, RAW_PAGES_DIR, load_settings, load_sources
from .vector_store import build_vector_store


def crawl_to_disk(max_pages: int = 200, max_depth: int = 2) -> int:
    settings = load_settings()
    allowed_domains, sources, category_keywords = load_sources()
    crawler = WebCrawler(allowed_domains, sources, category_keywords, settings)
    documents = crawler.crawl(max_pages=max_pages, max_depth=max_depth)
    return write_jsonl(DOCUMENTS_PATH, [document.to_dict() for document in documents])


def ingest_pages_to_disk(pages_dir: Path = RAW_PAGES_DIR, documents_path: Path = DOCUMENTS_PATH) -> int:
    _allowed_domains, _sources, category_keywords = load_sources()
    html_source = SourceConfig(url="", source_site="本地原文", category="原文")
    pdf_source = SourceConfig(url="", source_site="本地PDF", category="原文")
    documents: list[Document] = []
    seen_checksums: set[str] = set()

    if not pages_dir.exists():
        return write_jsonl(documents_path, [])

    for path in sorted(pages_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".html", ".pdf"}:
            continue
        url = path.resolve().as_uri()
        if path.suffix.lower() == ".pdf":
            title, content = parse_pdf_file(path)
            source = pdf_source
        else:
            title, content, _links = parse_html_page(path.read_bytes(), url)
            source = html_source
        if len(content) < TEXT_MIN_LENGTH:
            continue
        if is_navigation_index_page(title, content, url):
            continue
        document = make_document(url, title, content, source, category_keywords)
        if document.checksum in seen_checksums:
            continue
        documents.append(document)
        seen_checksums.add(document.checksum)
    return write_jsonl(documents_path, [document.to_dict() for document in documents])


def parse_pdf_file(path: Path) -> tuple[str, str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("读取 PDF 需要安装依赖：pip install pypdf") from exc

    reader = PdfReader(str(path))
    metadata_title = None
    if reader.metadata is not None:
        metadata_title = reader.metadata.title
    title = clean_text(str(metadata_title)) if metadata_title else path.stem

    page_texts: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = clean_text(page.extract_text() or "")
        if text:
            page_texts.append(f"第 {index} 页 {text}")

    return title or path.stem, clean_text("\n\n".join(page_texts))


def load_documents() -> list[Document]:
    return [Document.from_dict(row) for row in read_jsonl(DOCUMENTS_PATH)]


def load_chunks() -> list[Chunk]:
    return [Chunk.from_dict(row) for row in read_jsonl(CHUNKS_PATH)]


def index_documents() -> tuple[int, int]:
    documents = load_documents()
    chunks = make_chunks(documents)
    write_jsonl(CHUNKS_PATH, [chunk.to_dict() for chunk in chunks])
    settings = load_settings()
    provider = build_embedding_provider(settings)
    store = build_vector_store(settings)
    store.build(chunks, provider)
    return len(documents), len(chunks)


def build_rag_service():
    from .rag import RagService

    settings = load_settings()
    provider = build_embedding_provider(settings)
    store = build_vector_store(settings)
    store.load()
    return RagService(store, provider, settings)
