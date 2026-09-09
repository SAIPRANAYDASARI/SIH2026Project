"""HTML → Block list.

Walks the document in source order, converting headings and paragraphs to
plain-text blocks and tables to markdown-table blocks (never flattened
prose, per the brief). Container elements (div/section/article/ul/ol) are
descended into; content elements (h1-h6, p, li, table) are converted and not
descended into further, so a `<td>` never turns into a spurious paragraph
block on top of its table.
"""

from __future__ import annotations

from bs4 import BeautifulSoup
from bs4.element import PageElement, Tag

from ingestion.parsing.blocks import Block, BlockType

_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_CONTENT_TAGS = {*_HEADING_TAGS.keys(), "p", "li", "table"}
_CONTAINER_TAGS = {"div", "section", "article", "main", "body", "ul", "ol", "html"}


def _table_to_markdown(table: Tag) -> str:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [cell.get_text(strip=True) for cell in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)

    if not rows:
        return ""

    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]

    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _walk(node: PageElement) -> list[Block]:
    blocks: list[Block] = []
    if not isinstance(node, Tag):
        return blocks

    for child in node.find_all(recursive=False):
        if not isinstance(child, Tag):
            continue

        name = child.name.lower() if child.name else ""

        if name in _HEADING_TAGS:
            text = child.get_text(strip=True)
            if text:
                blocks.append(Block(BlockType.HEADING, text, heading_level=_HEADING_TAGS[name]))
        elif name == "table":
            markdown = _table_to_markdown(child)
            if markdown:
                blocks.append(Block(BlockType.TABLE, markdown))
        elif name in {"p", "li"}:
            text = child.get_text(" ", strip=True)
            if text:
                blocks.append(Block(BlockType.PARAGRAPH, text))
        elif name in _CONTAINER_TAGS:
            blocks.extend(_walk(child))
        # Other tags (script, style, nav, footer, header, aside, form, ...)
        # are intentionally ignored — boilerplate, not document content.

    return blocks


def parse_html(content: bytes) -> list[Block]:
    soup = BeautifulSoup(content, "lxml")
    root = soup.body or soup
    return _walk(root)
