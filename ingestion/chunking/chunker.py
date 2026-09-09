"""Clause-aware chunking.

Groups a document's `Block`s into chunks of `chunking.tokens`' target size,
with word-based overlap between consecutive chunks, while treating every
block as atomic — a table or a clause paragraph is never split across two
chunks, even if that means a chunk falls outside the target range (a very
large table becomes its own oversized chunk; a very small tail becomes its
own undersized final chunk). This is the deliberate trade-off the brief
asks for ("never split a table or a numbered clause across chunks") over a
strict token-count guarantee.

A heading also forces a chunk boundary once the current chunk has reached
the minimum target size, so section boundaries in the source document tend
to line up with chunk boundaries — useful for `section_path` staying
meaningful, though not treated as a hard rule the way tables/clauses are.
"""

from __future__ import annotations

from dataclasses import dataclass

from ingestion.chunking.tokens import (
    approx_token_count,
    overlap_word_count,
    target_max_words,
    target_min_words,
)
from ingestion.parsing.blocks import Block, BlockType


@dataclass(frozen=True)
class ChunkDraft:
    text: str
    section_path: str | None
    clause_number: str | None
    page_number: int | None
    context_header: str
    token_count: int


class _HeadingStack:
    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []

    def push(self, level: int, text: str) -> None:
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, text))

    def path(self) -> str | None:
        if not self._stack:
            return None
        return " > ".join(text for _, text in self._stack)


class _ChunkBuffer:
    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self.section_path: str | None = None

    def word_count(self) -> int:
        return sum(len(b.text.split()) for b in self.blocks)

    def is_empty(self) -> bool:
        return not self.blocks

    def clause_number(self) -> str | None:
        for block in self.blocks:
            if block.clause_number:
                return block.clause_number
        return None

    def page_number(self) -> int | None:
        for block in self.blocks:
            if block.page_number is not None:
                return block.page_number
        return None

    def body_text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)


def _build_context_header(
    doc_label: str, section_path: str | None, clause_number: str | None, page_number: int | None
) -> str:
    parts = [doc_label]
    if section_path:
        parts.append(section_path)
    if clause_number:
        parts.append(f"Clause {clause_number}")
    header = " > ".join(parts)
    if page_number is not None:
        header += f" (p. {page_number})"
    return header


def _finalize(buffer: _ChunkBuffer, doc_label: str, overlap_words: list[str]) -> ChunkDraft:
    text = buffer.body_text()
    if overlap_words:
        text = " ".join(overlap_words) + "\n\n" + text

    return ChunkDraft(
        text=text,
        section_path=buffer.section_path,
        clause_number=buffer.clause_number(),
        page_number=buffer.page_number(),
        context_header=_build_context_header(
            doc_label, buffer.section_path, buffer.clause_number(), buffer.page_number()
        ),
        token_count=approx_token_count(text),
    )


def chunk_blocks(blocks: list[Block], *, doc_label: str) -> list[ChunkDraft]:
    """`doc_label` is what the context header is anchored to — normally the
    IS number, falling back to the document title (see
    `ingestion.pipeline.process_document`)."""
    headings = _HeadingStack()
    buffer = _ChunkBuffer()
    chunks: list[ChunkDraft] = []
    min_words, max_words, overlap_n = target_min_words(), target_max_words(), overlap_word_count()

    def close_current(next_overlap: list[str]) -> list[str]:
        if buffer.is_empty():
            return next_overlap
        chunks.append(_finalize(buffer, doc_label, next_overlap))
        tail = buffer.body_text().split()[-overlap_n:] if overlap_n else []
        buffer.blocks.clear()
        return tail

    pending_overlap: list[str] = []

    for block in blocks:
        if block.type is BlockType.HEADING:
            if buffer.word_count() >= min_words:
                pending_overlap = close_current(pending_overlap)
            headings.push(block.heading_level or 1, block.text)
            if buffer.is_empty():
                buffer.section_path = headings.path()
            buffer.blocks.append(block)
            continue

        # A table gets its own chunk rather than being appended to an
        # already-substantial buffer of preceding prose, so a table's
        # neighbourhood context doesn't crowd it against the max — it still
        # merges into a small/empty buffer, since forcing every table into
        # its own chunk regardless of surrounding content would defeat the
        # point of grouping at all.
        if block.type is BlockType.TABLE and buffer.word_count() >= min_words:
            pending_overlap = close_current(pending_overlap)

        if buffer.is_empty():
            buffer.section_path = headings.path()

        buffer.blocks.append(block)

        if buffer.word_count() >= max_words:
            pending_overlap = close_current(pending_overlap)

    if not buffer.is_empty():
        close_current(pending_overlap)

    return chunks
