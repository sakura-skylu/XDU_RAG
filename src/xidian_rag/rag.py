from __future__ import annotations

import re
from dataclasses import replace

from .categorizer import keyword_score
from .content_filter import navigation_noise_score
from .embeddings import EmbeddingProvider
from .io import read_jsonl
from .models import Answer, Chunk, Citation, SearchHit
from .settings import CHUNKS_PATH, Settings
from .vector_store import LocalVectorStore

REFUSAL = "未在已收录官方资料中找到依据。请更换问法，或先更新知识库后再查询。"
MIN_RELIABLE_SCORE = 0.08
MAX_CONTEXT_CHARS = 900
MAX_HITS_PER_DOCUMENT = 1
DIRECT_API_CONTEXT_HITS = 12
QUESTION_STOP_CHARS = set("的了呢吗啊和与及或在是有请问哪些什么怎么如何一下一个可以")


def make_snippet(text: str, limit: int = 220) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "..."


def question_terms(question: str) -> set[str]:
    words = {word.lower() for word in re.findall(r"[A-Za-z0-9]+", question) if len(word) > 1}
    compact = re.sub(r"\s+", "", question.lower())
    words.update(char for char in compact if "\u4e00" <= char <= "\u9fff" and char not in QUESTION_STOP_CHARS)
    for size in (2, 3, 4):
        words.update(compact[index : index + size] for index in range(max(len(compact) - size + 1, 0)))
    return words


def is_noisy_hit(hit: SearchHit) -> bool:
    return navigation_noise_score(hit.chunk.text) >= 0.6


def evidence_score(question: str, hit: SearchHit) -> float:
    chunk = hit.chunk
    terms = question_terms(question)
    combined = f"{chunk.title} {chunk.text}".lower()
    term_hits = sum(1 for term in terms if term and term in combined)
    term_score = term_hits / max(len(terms), 1)
    lexical = keyword_score(question, combined)
    noise_penalty = navigation_noise_score(chunk.text) * 0.25
    title_bonus = 0.04 if any(term in chunk.title.lower() for term in terms if len(term) >= 2) else 0.0
    return hit.score * 0.65 + lexical * 0.2 + term_score * 0.15 + title_bonus - noise_penalty


def select_evidence_hits(question: str, hits: list[SearchHit], limit: int) -> list[SearchHit]:
    reliable_hits = [hit for hit in hits if hit.score >= MIN_RELIABLE_SCORE]
    clean_hits = [hit for hit in reliable_hits if not is_noisy_hit(hit)]
    candidates = clean_hits or reliable_hits
    candidates = sorted(candidates, key=lambda hit: evidence_score(question, hit), reverse=True)

    selected: list[SearchHit] = []
    per_doc: dict[str, int] = {}
    for hit in candidates:
        doc_count = per_doc.get(hit.chunk.doc_id, 0)
        if doc_count >= MAX_HITS_PER_DOCUMENT:
            continue
        selected.append(hit)
        per_doc[hit.chunk.doc_id] = doc_count + 1
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        seen = {hit.chunk.chunk_id for hit in selected}
        for hit in candidates:
            if hit.chunk.chunk_id in seen:
                continue
            selected.append(hit)
            if len(selected) >= limit:
                break
    return selected


def chunk_relevance_score(question: str, chunk: Chunk) -> float:
    terms = question_terms(question)
    combined = f"{chunk.title} {chunk.text}".lower()
    term_hits = sum(1 for term in terms if term and term in combined)
    term_score = term_hits / max(len(terms), 1)
    lexical = keyword_score(question, combined)
    title_hits = sum(1 for term in terms if len(term) >= 2 and term in chunk.title.lower())
    title_score = min(title_hits / 3, 1.0)
    noise_penalty = navigation_noise_score(chunk.text) * 0.18
    return lexical * 0.5 + term_score * 0.35 + title_score * 0.15 - noise_penalty


def select_direct_api_hits(question: str, chunks: list[Chunk], limit: int, category: str | None = None) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for chunk in chunks:
        if category and category != "全部" and chunk.category != category:
            continue
        score = chunk_relevance_score(question, chunk)
        if score <= 0:
            continue
        hits.append(SearchHit(chunk=chunk, score=score))

    hits.sort(key=lambda hit: hit.score, reverse=True)
    clean_hits = [hit for hit in hits if not is_noisy_hit(hit)] or hits
    selected: list[SearchHit] = []
    per_doc: dict[str, int] = {}
    for hit in clean_hits:
        doc_count = per_doc.get(hit.chunk.doc_id, 0)
        if doc_count >= MAX_HITS_PER_DOCUMENT:
            continue
        selected.append(hit)
        per_doc[hit.chunk.doc_id] = doc_count + 1
        if len(selected) >= limit:
            break
    return selected


def best_relevant_snippet(question: str, text: str, limit: int = 220) -> str:
    clean = " ".join(text.split())
    parts = [
        part.strip()
        for part in re.split(r"(?<=[。！？；])", clean)
        if part.strip() and navigation_noise_score(part) < 0.6
    ]
    if not parts:
        return make_snippet(clean, limit)

    question_term_set = question_terms(question)
    ranked = sorted(
        enumerate(parts),
        key=lambda item: keyword_score(question, item[1]) + len(question_term_set & question_terms(item[1])) * 0.03,
        reverse=True,
    )
    selected_indexes = sorted(index for index, _part in ranked[:3])
    selected = " ".join(parts[index] for index in selected_indexes)
    if len(selected) < 80 and selected_indexes:
        tail_index = min(selected_indexes[-1] + 1, len(parts) - 1)
        selected = " ".join(parts[index] for index in sorted({*selected_indexes, tail_index}))
    return make_snippet(selected or clean, limit)


def context_snippet(question: str, text: str) -> str:
    if navigation_noise_score(text) < 0.35:
        return make_snippet(text, MAX_CONTEXT_CHARS)
    return best_relevant_snippet(question, text, MAX_CONTEXT_CHARS)


def hits_to_citations(hits: list[SearchHit], question: str | None = None) -> list[Citation]:
    citations: list[Citation] = []
    seen_urls: set[str] = set()
    for hit in hits:
        chunk = hit.chunk
        key = f"{chunk.url}#{chunk.chunk_id}"
        if key in seen_urls:
            continue
        seen_urls.add(key)
        citations.append(
            Citation(
                title=chunk.title,
                url=chunk.url,
                source_site=chunk.source_site,
                category=chunk.category,
                publish_date=chunk.publish_date,
                snippet=best_relevant_snippet(question, chunk.text) if question else make_snippet(chunk.text),
                score=round(hit.score, 4),
            )
        )
    return citations


class OpenAICompatibleChatClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for API chat")
        self.settings = settings

    def complete(self, question: str, hits: list[SearchHit]) -> str:
        import requests

        context = "\n\n".join(
            f"[{index}] 标题：{hit.chunk.title}\n来源：{hit.chunk.url}\n"
            f"发布时间：{hit.chunk.publish_date or '未知'}\n"
            f"片段：{context_snippet(question, hit.chunk.text)}"
            for index, hit in enumerate(hits, start=1)
        )
        prompt = (
            "你是西安电子科技大学官网资料检索助手。只能根据给定资料回答，不得编造资料外信息。\n"
            "请按以下固定结构输出：\n"
            "直接结论：用1-2句话回答问题，关键事实后标注引用编号，例如[1]。\n"
            "要点说明：列出2-4条有依据的要点，每条都必须带引用编号。\n"
            "资料不足：只要资料没有覆盖课程设置、培养方案、报名时限、适用对象等用户可能关心的具体细节，"
            "就明确列出缺口；只有问题所需信息完全覆盖时，才写“未发现明显缺口”。\n"
            "如果命中资料彼此无关或证据很弱，要优先说明无法确认，不要勉强概括。\n\n"
            f"问题：{question}\n\n资料：\n{context}"
        )
        response = requests.post(
            f"{self.settings.openai_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.openai_chat_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你只根据检索资料作答。每个关键事实都要标注引用编号；"
                            "缺少依据、资料不相关或证据不足时必须说明无法确认。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            },
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"]["content"].strip()


class RagService:
    def __init__(
        self,
        store: LocalVectorStore,
        provider: EmbeddingProvider,
        settings: Settings,
        chat_client_cls: type[OpenAICompatibleChatClient] = OpenAICompatibleChatClient,
    ) -> None:
        self.store = store
        self.provider = provider
        self.settings = settings
        self.chat_client_cls = chat_client_cls

    def ask(self, question: str, top_k: int = 5, category: str | None = None) -> Answer:
        if self.settings.use_direct_api_chat and self.settings.openai_api_key:
            return self._ask_direct_api(question, top_k=top_k, category=category)

        search_limit = max(top_k * 4, 12)
        hits = self.store.search(question, self.provider, top_k=search_limit, category=category)
        evidence_hits = select_evidence_hits(question, hits, limit=top_k)
        if not evidence_hits:
            return Answer(answer=REFUSAL, citations=[], has_evidence=False, mode="refusal")

        citations = hits_to_citations(evidence_hits, question)
        if self.settings.use_api_chat and self.settings.openai_api_key:
            try:
                answer = self.chat_client_cls(self.settings).complete(question, evidence_hits)
                return Answer(answer=answer, citations=citations, has_evidence=True, mode="api")
            except Exception as exc:
                fallback = self._extractive_answer(question, evidence_hits)
                fallback += f"\n\n提示：API 生成失败，已使用抽取式回答。原因：{exc}"
                return Answer(answer=fallback, citations=citations, has_evidence=True, mode="extractive-fallback")

        return Answer(
            answer=self._extractive_answer(question, evidence_hits),
            citations=citations,
            has_evidence=True,
            mode="extractive",
        )

    def _ask_direct_api(self, question: str, top_k: int, category: str | None) -> Answer:
        context_limit = max(top_k * 3, DIRECT_API_CONTEXT_HITS)
        hits = select_direct_api_hits(question, self._load_available_chunks(), limit=context_limit, category=category)
        evidence_hits = hits[:top_k]
        if not evidence_hits:
            return Answer(answer=REFUSAL, citations=[], has_evidence=False, mode="direct-api-refusal")

        citations = hits_to_citations(evidence_hits, question)
        try:
            chat_settings = replace(self.settings, use_direct_api_chat=False, use_api_chat=True)
            answer = self.chat_client_cls(chat_settings).complete(question, hits)
            return Answer(answer=answer, citations=citations, has_evidence=True, mode="direct-api")
        except Exception as exc:
            fallback = self._extractive_answer(question, evidence_hits)
            fallback += f"\n\n提示：直接 API 生成失败，已使用本地候选资料抽取式回答。原因：{exc}"
            return Answer(answer=fallback, citations=citations, has_evidence=True, mode="direct-api-fallback")

    def _load_available_chunks(self) -> list[Chunk]:
        chunks = list(getattr(self.store, "chunks", []) or [])
        if chunks:
            return chunks
        if not CHUNKS_PATH.exists():
            return []
        return [Chunk.from_dict(row) for row in read_jsonl(CHUNKS_PATH)]

    def _extractive_answer(self, question: str, hits: list[SearchHit]) -> str:
        lines = ["直接结论：根据已收录的西电官方资料，当前能确认的信息如下；未覆盖的细节需以原文或后续更新资料为准。"]
        lines.append("要点说明：")
        for index, hit in enumerate(hits[:3], start=1):
            date = hit.chunk.publish_date or "发布时间未知"
            snippet = best_relevant_snippet(question, hit.chunk.text)
            lines.append(f"{index}. {hit.chunk.title}（{hit.chunk.source_site}，{date}）：{snippet} [{index}]")
        lines.append("资料不足：如问题涉及具体流程、课程安排或报名时限，当前回答只覆盖引用片段中明确出现的信息。")
        return "\n".join(lines)
