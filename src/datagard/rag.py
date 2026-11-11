"""Deterministic lexical runbook chunking and retrieval for a small local corpus."""

import logging
import math
import re
from pathlib import Path

from datagard.config import RetrievalSettings
from datagard.contracts import RunbookChunk

logger = logging.getLogger(__name__)


class RunbookRetriever:
    """Index Markdown heading sections and rank them with TF-IDF cosine similarity."""

    def __init__(self, settings: RetrievalSettings, corpus_dir: Path) -> None:
        self._top_k = settings.top_k
        self._chunks = _load_chunks(corpus_dir)
        if not self._chunks:
            raise ValueError(f"Runbook corpus is empty: {corpus_dir}")

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def retrieve(self, query: str) -> tuple[RunbookChunk, ...]:
        """Return the highest-scoring sections with stable source references."""

        query_terms = _terms(query)
        if not query_terms:
            return ()
        document_terms = [_terms(chunk[3]) for chunk in self._chunks]
        document_frequency: dict[str, int] = {}
        for terms in document_terms:
            for term in set(terms):
                document_frequency[term] = document_frequency.get(term, 0) + 1
        query_vector = _tfidf(query_terms, document_frequency, len(self._chunks))
        scored: list[RunbookChunk] = []
        for chunk, terms in zip(self._chunks, document_terms, strict=True):
            vector = _tfidf(terms, document_frequency, len(self._chunks))
            score = _cosine(query_vector, vector)
            if score > 0:
                scored.append(RunbookChunk(
                    document_id=chunk[0], section_id=chunk[1], title=chunk[2], score=score, text=chunk[3]
                ))
        results = tuple(sorted(scored, key=lambda item: (-item.score, item.document_id, item.section_id))[: self._top_k])
        logger.info("runbooks retrieved", extra={"query_terms": len(query_terms), "result_count": len(results)})
        return results


def _load_chunks(corpus_dir: Path) -> tuple[tuple[str, str, str, str], ...]:
    chunks: list[tuple[str, str, str, str]] = []
    for path in sorted(corpus_dir.glob("*.md")):
        document_id = path.stem
        current_title = "Overview"
        current_lines: list[str] = []
        section_index = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                if current_lines:
                    chunks.append((document_id, f"{document_id}#{section_index:02d}", current_title, "\n".join(current_lines).strip()))
                    current_lines = []
                current_title = line.lstrip("# ").strip()
                section_index += 1
            else:
                current_lines.append(line)
        if current_lines:
            chunks.append((document_id, f"{document_id}#{section_index:02d}", current_title, "\n".join(current_lines).strip()))
    return tuple(chunk for chunk in chunks if chunk[3])


def _terms(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", text.lower()))


def _tfidf(terms: tuple[str, ...], document_frequency: dict[str, int], document_count: int) -> dict[str, float]:
    frequencies: dict[str, int] = {}
    for term in terms:
        frequencies[term] = frequencies.get(term, 0) + 1
    return {
        term: (1.0 + math.log(count)) * (math.log((document_count + 1) / (document_frequency.get(term, 0) + 1)) + 1.0)
        for term, count in frequencies.items()
    }


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    numerator = sum(value * right.get(term, 0.0) for term, value in left.items())
    if numerator == 0:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return numerator / (left_norm * right_norm)
