from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import xidian_rag.crawler as crawler_module
from xidian_rag.categorizer import categorize
from xidian_rag.chunking import make_chunks, split_text
from xidian_rag.crawler import make_doc_id, raw_page_path, save_raw_page_snapshot
from xidian_rag.embeddings import HashEmbeddingProvider
from xidian_rag.models import Document, SearchHit
from xidian_rag.pipeline import ingest_pages_to_disk
from xidian_rag.rag import REFUSAL, RagService, select_direct_api_hits, select_evidence_hits
from xidian_rag.settings import Settings
from xidian_rag.vector_store import LocalVectorStore


class CoreTests(unittest.TestCase):
    def test_split_text_keeps_short_text(self) -> None:
        self.assertEqual(split_text("西电 推免 政策", max_chars=20), ["西电 推免 政策"])

    def test_categorize_prefers_keyword_match(self) -> None:
        category = categorize(
            "关于推荐免试研究生工作的通知",
            "通知",
            {"保研": ["推免", "推荐免试"], "竞赛": ["比赛"]},
        )
        self.assertEqual(category, "保研")

    def test_raw_page_snapshot_keeps_original_bytes(self) -> None:
        url = "https://gr.xidian.edu.cn/example"
        payload = b"<html><body> raw \xe8\xa5\xbf\xe7\x94\xb5 </body></html>"
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = crawler_module.RAW_PAGES_DIR
            crawler_module.RAW_PAGES_DIR = Path(tmp)
            try:
                save_raw_page_snapshot(url, payload)
                path = raw_page_path(url)
                self.assertEqual(path.name, f"{make_doc_id(url)}.html")
                self.assertEqual(path.read_bytes(), payload)
            finally:
                crawler_module.RAW_PAGES_DIR = original_dir

    def test_ingest_pages_generates_documents_from_html(self) -> None:
        repeated_text = "学校发布推荐免试研究生工作通知，说明推免资格、综合成绩和申请流程。"
        html = f"""
        <html>
          <head><title>推荐免试研究生工作通知</title></head>
          <body><article>{repeated_text * 4}</article></body>
        </html>
        """
        with tempfile.TemporaryDirectory() as tmp:
            pages_dir = Path(tmp) / "pages"
            documents_path = Path(tmp) / "documents.jsonl"
            pages_dir.mkdir()
            (pages_dir / "notice.html").write_text(html, encoding="utf-8")

            count = ingest_pages_to_disk(pages_dir=pages_dir, documents_path=documents_path)

            self.assertEqual(count, 1)
            document = Document.from_dict(json.loads(documents_path.read_text(encoding="utf-8")))
            self.assertEqual(document.title, "推荐免试研究生工作通知")
            self.assertIn("推免资格", document.content)
            self.assertEqual(document.source_site, "本地原文")

    def test_ingest_pages_generates_documents_from_pdf(self) -> None:
        repeated_text = "学校发布推荐免试研究生工作通知，说明推免资格、综合成绩和申请流程。"
        with tempfile.TemporaryDirectory() as tmp:
            pages_dir = Path(tmp) / "pages"
            documents_path = Path(tmp) / "documents.jsonl"
            pages_dir.mkdir()
            (pages_dir / "notice.pdf").write_bytes(b"%PDF placeholder")

            with patch(
                "xidian_rag.pipeline.parse_pdf_file",
                return_value=("推荐免试研究生工作通知", repeated_text * 4),
            ):
                count = ingest_pages_to_disk(pages_dir=pages_dir, documents_path=documents_path)

            self.assertEqual(count, 1)
            document = Document.from_dict(json.loads(documents_path.read_text(encoding="utf-8")))
            self.assertEqual(document.title, "推荐免试研究生工作通知")
            self.assertIn("推免资格", document.content)
            self.assertEqual(document.source_site, "本地PDF")

    def test_ingest_pages_skips_short_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pages_dir = Path(tmp) / "pages"
            documents_path = Path(tmp) / "documents.jsonl"
            pages_dir.mkdir()
            (pages_dir / "empty.html").write_text("<html><title>空页面</title><body>太短</body></html>", encoding="utf-8")

            count = ingest_pages_to_disk(pages_dir=pages_dir, documents_path=documents_path)

            self.assertEqual(count, 0)
            self.assertEqual(documents_path.read_text(encoding="utf-8"), "")

    def test_ingest_pages_skips_navigation_homepage(self) -> None:
        menu = (
            "西安电子科技大学 书记信箱 校长信箱 学生邮件 教工邮件 一网通办 信息公开 综合信息网 "
            "教师主页 学生 教职工 校友 来访者 学校概况 学校简介 学校章程 现任领导 历任领导 "
            "机构设置 教育教学 合作交流 招生就业 办学资源 查看更多 常用系统 访问量 "
        )
        html = f"""
        <html>
          <head><title>西安电子科技大学</title></head>
          <body>{menu * 8}</body>
        </html>
        """
        with tempfile.TemporaryDirectory() as tmp:
            pages_dir = Path(tmp) / "pages"
            documents_path = Path(tmp) / "documents.jsonl"
            pages_dir.mkdir()
            (pages_dir / "home.html").write_text(html, encoding="utf-8")

            count = ingest_pages_to_disk(pages_dir=pages_dir, documents_path=documents_path)

            self.assertEqual(count, 0)
            self.assertEqual(documents_path.read_text(encoding="utf-8"), "")

    def test_rag_refuses_empty_store(self) -> None:
        settings = Settings(
            None,
            "https://api.openai.com/v1",
            "chat",
            "embed",
            None,
            "https://api.openai.com/v1",
            None,
            False,
            False,
            False,
            "local",
            1,
            0,
        )
        store = LocalVectorStore(path=Path(tempfile.gettempdir()) / "missing-xidian-rag-index.json")
        provider = HashEmbeddingProvider()
        service = RagService(store, provider, settings)
        result = service.ask("保研政策有哪些要求")
        self.assertFalse(result.has_evidence)
        self.assertEqual(result.answer, REFUSAL)

    def test_local_vector_search_finds_related_chunk(self) -> None:
        document = Document(
            doc_id="doc1",
            title="推荐免试研究生工作通知",
            url="https://gr.xidian.edu.cn/example",
            source_site="研究生院",
            category="保研",
            publish_date="2026-05-01",
            content="学校发布推荐免试研究生工作通知，说明推免资格、综合成绩和申请流程。",
            crawl_time="2026-05-13T00:00:00Z",
            checksum="abc",
        )
        chunks = make_chunks([document], max_chars=80)
        provider = HashEmbeddingProvider()
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalVectorStore(path=Path(tmp) / "index.json")
            store.build(chunks, provider)
            hits = store.search("保研 推免 资格", provider, top_k=1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].chunk.category, "保研")

    def test_evidence_selection_filters_navigation_noise(self) -> None:
        noisy_document = Document(
            doc_id="nav",
            title="西安电子科技大学",
            url="https://www.xidian.edu.cn/",
            source_site="西电主站",
            category="原文",
            publish_date=None,
            content=(
                "书记信箱 校长信箱 学生邮件 教工邮件 一网通办 信息公开 综合信息网 "
                "教师主页 学校概况 机构设置 教育教学 合作交流 招生就业 办学资源 查看更多"
            ),
            crawl_time="2026-05-13T00:00:00Z",
            checksum="nav",
        )
        useful_document = Document(
            doc_id="useful",
            title="推荐免试研究生工作通知",
            url="https://gr.xidian.edu.cn/example",
            source_site="研究生院",
            category="保研",
            publish_date="2026-05-01",
            content="学校发布推荐免试研究生工作通知，明确推免资格、报名流程和复试考核安排。",
            crawl_time="2026-05-13T00:00:00Z",
            checksum="useful",
        )
        noisy_chunk = make_chunks([noisy_document], max_chars=300)[0]
        useful_chunk = make_chunks([useful_document], max_chars=300)[0]
        hits = [SearchHit(noisy_chunk, 0.2), SearchHit(useful_chunk, 0.12)]

        selected = select_evidence_hits("保研预报名有什么要求", hits, limit=2)

        self.assertEqual([hit.chunk.doc_id for hit in selected], ["useful"])

    def test_extractive_answer_uses_relevant_sentence(self) -> None:
        document = Document(
            doc_id="doc1",
            title="计算机科学与技术学院介绍",
            url="https://zsb.xidian.edu.cn/example",
            source_site="本科招生信息网",
            category="教务",
            publish_date=None,
            content=(
                "书记信箱 校长信箱 学生邮件 教工邮件 一网通办 信息公开 综合信息网。"
                "计算机科学与技术是国家双一流建设学科，全国最早设立的计算机专业，具有较高国际声誉。"
                "更多栏目 学校概况 机构设置 教育教学 招生就业。"
            ),
            crawl_time="2026-05-13T00:00:00Z",
            checksum="abc",
        )
        hit = SearchHit(make_chunks([document], max_chars=300)[0], 0.2)
        settings = Settings(
            None,
            "https://api.openai.com/v1",
            "chat",
            "embed",
            None,
            "https://api.openai.com/v1",
            None,
            False,
            False,
            False,
            "local",
            1,
            0,
        )
        service = RagService(LocalVectorStore(), HashEmbeddingProvider(), settings)

        answer = service._extractive_answer("计算机专业介绍", [hit])

        self.assertIn("全国最早设立的计算机专业", answer)
        self.assertNotIn("书记信箱 校长信箱", answer)

    def test_direct_api_selection_uses_text_relevance_without_embeddings(self) -> None:
        useful_document = Document(
            doc_id="useful",
            title="本科招生专业介绍",
            url="https://zsb.xidian.edu.cn/example",
            source_site="本科招生信息网",
            category="教务",
            publish_date=None,
            content="计算机科学与技术是国家双一流建设学科，全国最早设立的计算机专业之一。",
            crawl_time="2026-05-13T00:00:00Z",
            checksum="useful",
        )
        unrelated_document = Document(
            doc_id="other",
            title="校园生活服务通知",
            url="https://xg.xidian.edu.cn/example",
            source_site="学生工作部",
            category="生活",
            publish_date=None,
            content="学校发布宿舍维修和校园卡服务安排。",
            crawl_time="2026-05-13T00:00:00Z",
            checksum="other",
        )
        chunks = make_chunks([unrelated_document, useful_document], max_chars=120)

        selected = select_direct_api_hits("计算机专业介绍", chunks, limit=2)

        self.assertEqual(selected[0].chunk.doc_id, "useful")

    def test_direct_api_mode_skips_embedding_search(self) -> None:
        class FailingProvider:
            def embed(self, texts: list[str]) -> list[list[float]]:
                raise AssertionError("direct API mode should not embed queries")

        class FakeChatClient:
            def __init__(self, settings: Settings) -> None:
                self.settings = settings

            def complete(self, question: str, hits: list[SearchHit]) -> str:
                return f"直接结论：{hits[0].chunk.title} [1]"

        document = Document(
            doc_id="doc1",
            title="计算机科学与技术学院介绍",
            url="https://zsb.xidian.edu.cn/example",
            source_site="本科招生信息网",
            category="教务",
            publish_date=None,
            content="计算机科学与技术是国家双一流建设学科，全国最早设立的计算机专业之一。",
            crawl_time="2026-05-13T00:00:00Z",
            checksum="abc",
        )
        chunks = make_chunks([document], max_chars=120)
        store = LocalVectorStore()
        store.chunks = chunks
        settings = Settings(
            "key",
            "https://api.openai.com/v1",
            "chat",
            "embed",
            "key",
            "https://api.openai.com/v1",
            None,
            False,
            False,
            True,
            "local",
            1,
            0,
        )
        service = RagService(store, FailingProvider(), settings, chat_client_cls=FakeChatClient)

        result = service.ask("计算机专业介绍")

        self.assertEqual(result.mode, "direct-api")
        self.assertTrue(result.has_evidence)
        self.assertIn("计算机科学与技术学院介绍", result.answer)


if __name__ == "__main__":
    unittest.main()
