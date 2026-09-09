"""Chunker: groups blocks into the target token range, never splits a table
or a numbered-clause paragraph across chunks, and overlaps consecutive
chunks by roughly the configured ratio."""

from __future__ import annotations

from ingestion.chunking.chunker import chunk_blocks
from ingestion.chunking.tokens import TARGET_MAX_TOKENS, TARGET_MIN_TOKENS, approx_token_count
from ingestion.parsing.blocks import Block, BlockType

DOC_LABEL = "IS 15111"


def _paragraph(words: int, tag: str = "p") -> Block:
    return Block(BlockType.PARAGRAPH, " ".join(f"{tag}{i}" for i in range(words)))


def test_small_document_becomes_one_chunk() -> None:
    blocks = [
        Block(BlockType.HEADING, "Scope", heading_level=1),
        _paragraph(50),
    ]
    chunks = chunk_blocks(blocks, doc_label=DOC_LABEL)

    assert len(chunks) == 1
    assert "Scope" in chunks[0].context_header
    assert DOC_LABEL in chunks[0].context_header


def test_large_document_splits_into_multiple_chunks_near_target_size() -> None:
    # ~2500 words of paragraphs ≈ several target-sized chunks.
    blocks = [_paragraph(400, tag=f"b{i}_") for i in range(7)]
    chunks = chunk_blocks(blocks, doc_label=DOC_LABEL)

    assert len(chunks) >= 3
    # Every chunk except possibly the last should land near the target
    # token range (allowing some slack since blocks are atomic).
    for chunk in chunks[:-1]:
        assert chunk.token_count <= TARGET_MAX_TOKENS * 1.5


def test_table_is_never_split_and_gets_its_own_chunk_when_buffer_is_full() -> None:
    big_table_rows = "\n".join(f"| row{i} | value{i} |" for i in range(200))
    table_block = Block(BlockType.TABLE, "| a | b |\n| --- | --- |\n" + big_table_rows)

    blocks = [_paragraph(350), table_block, _paragraph(350)]
    chunks = chunk_blocks(blocks, doc_label=DOC_LABEL)

    table_chunks = [c for c in chunks if table_block.text in c.text]
    assert len(table_chunks) == 1
    # The table's full text appears verbatim and intact in exactly one chunk.
    assert table_block.text in table_chunks[0].text


def test_clause_paragraph_is_never_split() -> None:
    clause_text = "4.2.1 " + " ".join(f"word{i}" for i in range(900))
    blocks = [Block(BlockType.PARAGRAPH, clause_text)]

    chunks = chunk_blocks(blocks, doc_label=DOC_LABEL)

    matching = [c for c in chunks if clause_text in c.text]
    assert len(matching) == 1
    assert matching[0].clause_number == "4.2.1"


def test_consecutive_chunks_overlap() -> None:
    blocks = [_paragraph(400, tag=f"b{i}_") for i in range(6)]
    chunks = chunk_blocks(blocks, doc_label=DOC_LABEL)

    assert len(chunks) >= 2
    first_words = chunks[0].text.split()
    second_words = chunks[1].text.split()
    # The start of chunk 2 should contain some tail words from chunk 1
    # (the injected overlap), i.e. it's not a disjoint continuation.
    overlap_candidates = set(first_words[-40:])
    assert overlap_candidates & set(second_words[:60])


def test_heading_sets_section_path() -> None:
    blocks = [
        Block(BlockType.HEADING, "Part A: General", heading_level=1),
        _paragraph(TARGET_MIN_TOKENS + 50),
        Block(BlockType.HEADING, "Part B: Requirements", heading_level=1),
        _paragraph(TARGET_MIN_TOKENS + 50),
    ]
    chunks = chunk_blocks(blocks, doc_label=DOC_LABEL)

    section_paths = {c.section_path for c in chunks}
    assert "Part A: General" in section_paths
    assert "Part B: Requirements" in section_paths


def test_empty_input_produces_no_chunks() -> None:
    assert chunk_blocks([], doc_label=DOC_LABEL) == []


def test_approx_token_count_is_positive_for_nonempty_text() -> None:
    assert approx_token_count("some words here") > 0
    assert approx_token_count("") == 0
