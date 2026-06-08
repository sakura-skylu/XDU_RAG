from __future__ import annotations

import hashlib
import math
from typing import Protocol

from .settings import Settings


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class HashEmbeddingProvider:
    """Small deterministic fallback embedding for offline demos and tests."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        normalized = "".join(text.lower().split())
        features = self._features(normalized)
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _features(self, text: str) -> list[str]:
        if not text:
            return []
        chars = list(text)
        features = chars[:]
        features.extend(text[i : i + 2] for i in range(max(len(text) - 1, 0)))
        features.extend(text[i : i + 3] for i in range(max(len(text) - 2, 0)))
        return features


class OpenAICompatibleEmbeddingProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_embedding_api_key:
            raise ValueError("OPENAI_EMBEDDING_API_KEY or ZHIPU_API_KEY is required for API embeddings")
        self.settings = settings

    def embed(self, texts: list[str]) -> list[list[float]]:
        import requests

        payload = {"model": self.settings.openai_embedding_model, "input": texts}
        if self.settings.openai_embedding_dimensions is not None:
            payload["dimensions"] = self.settings.openai_embedding_dimensions

        response = requests.post(
            f"{self.settings.openai_embedding_base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.settings.openai_embedding_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return [item["embedding"] for item in payload["data"]]


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.use_api_embeddings:
        return OpenAICompatibleEmbeddingProvider(settings)
    return HashEmbeddingProvider()
