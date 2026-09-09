"""HTML parsing preserves document order, converts tables to markdown
(never flattened prose), and ignores boilerplate (nav/script/style)."""

from __future__ import annotations

from ingestion.parsing.blocks import BlockType
from ingestion.parsing.html_parser import parse_html


def test_headings_and_paragraphs_in_order() -> None:
    html = b"""
    <html><body>
        <h1>Compulsory Registration Scheme</h1>
        <p>Introductory paragraph.</p>
        <h2>4.2 Eligibility</h2>
        <p>Clause text about eligibility.</p>
    </body></html>
    """
    blocks = parse_html(html)

    types = [b.type for b in blocks]
    assert types == [
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.HEADING,
        BlockType.PARAGRAPH,
    ]
    assert blocks[0].text == "Compulsory Registration Scheme"
    assert blocks[0].heading_level == 1
    assert blocks[2].heading_level == 2
    assert blocks[2].clause_number == "4.2"


def test_table_becomes_markdown_not_flattened_prose() -> None:
    html = b"""
    <html><body>
        <table>
            <tr><th>Fee head</th><th>Amount (INR)</th></tr>
            <tr><td>Application fee</td><td>1000</td></tr>
            <tr><td>Marking fee</td><td>5000</td></tr>
        </table>
    </body></html>
    """
    blocks = parse_html(html)

    assert len(blocks) == 1
    assert blocks[0].type is BlockType.TABLE
    assert blocks[0].text.startswith("| Fee head | Amount (INR) |")
    assert "| --- | --- |" in blocks[0].text
    assert "| Application fee | 1000 |" in blocks[0].text


def test_boilerplate_tags_are_ignored() -> None:
    html = b"""
    <html><body>
        <nav>Site navigation</nav>
        <script>console.log("tracking")</script>
        <style>.foo { color: red; }</style>
        <p>Actual content.</p>
        <footer>Copyright 2026</footer>
    </body></html>
    """
    blocks = parse_html(html)

    assert len(blocks) == 1
    assert blocks[0].text == "Actual content."


def test_nested_containers_are_descended_into() -> None:
    html = b"""
    <html><body>
        <div><section><article>
            <h2>Nested heading</h2>
            <p>Nested paragraph</p>
        </article></section></div>
    </body></html>
    """
    blocks = parse_html(html)

    assert [b.type for b in blocks] == [BlockType.HEADING, BlockType.PARAGRAPH]
