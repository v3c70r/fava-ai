"""Optional OpenAI-compatible embeddings client.

Points at any ``/v1/embeddings`` endpoint (llama.cpp, Ollama, OpenAI, …). This
is optional: without it, document search uses the FTS5/BM25 index only.
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """Raised when the embedding endpoint is misconfigured or fails."""


class EmbeddingClient:
    def __init__(self, base_url: str = "", api_key: str = "", model: str = "",
                 timeout: int = 60, batch_size: int = 32):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.timeout = timeout
        self.batch_size = max(1, batch_size)

    @classmethod
    def from_config(cls, config: dict | None) -> "EmbeddingClient":
        config = config or {}

        def _int(key: str, default: int) -> int:
            try:
                return max(1, int(config.get(key, default)))
            except (TypeError, ValueError):
                return default

        return cls(
            base_url=str(config.get("base_url") or ""),
            api_key=str(config.get("api_key") or ""),
            model=str(config.get("model") or ""),
            timeout=_int("timeout", 60),
            batch_size=_int("batch_size", 32),
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.configured:
            raise EmbeddingError(
                "Embedding endpoint not configured (set documents.embedding.base_url and .model)"
            )
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed_batch(texts[start:start + self.batch_size]))
        return vectors

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = requests.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": batch},
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise EmbeddingError(f"Embedding request failed: {e}") from e

        if response.status_code != 200:
            raise EmbeddingError(
                f"Embedding endpoint returned HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )
        try:
            data = response.json().get("data")
        except ValueError as e:
            raise EmbeddingError("Embedding endpoint returned invalid JSON") from e
        if not isinstance(data, list) or len(data) != len(batch):
            raise EmbeddingError("Embedding endpoint returned an unexpected payload")

        ordered = sorted(data, key=lambda item: item.get("index", 0))
        try:
            return [[float(x) for x in item["embedding"]] for item in ordered]
        except (KeyError, TypeError, ValueError) as e:
            raise EmbeddingError("Embedding payload is missing vectors") from e

    def test_connection(self) -> tuple[bool, str]:
        try:
            vector = self.embed_one("ping")
        except EmbeddingError as e:
            return False, str(e)
        return True, f"{len(vector)} dimensions"
