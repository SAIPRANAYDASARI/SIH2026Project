"""The structural unit both parsers produce and the chunker consumes.

A `Block` is deliberately coarse-grained (one heading, one paragraph, one
table) rather than sentence- or token-level, because the chunker's job is to
*group* blocks into 400-800 token chunks without ever splitting one — so the
unit the chunker operates on has to already be "a table" or "a clause
paragraph" as a whole, not a fragment of one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

# Matches a leading clause/sub-clause numbering like "4.2.1", "4.2", "A.1",
# at the start of a heading or paragraph — the same identifier shape used
# throughout Indian Standards and BIS scheme documents.
CLAUSE_NUMBER_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+){0,4}|[A-Z]\.\d+(?:\.\d+)*)\b")


class BlockType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"


@dataclass(frozen=True)
class Block:
    type: BlockType
    text: str  # for TABLE, this is already markdown-table syntax
    heading_level: int | None = None  # 1-6 for HEADING blocks, else None
    page_number: int | None = None

    @property
    def clause_number(self) -> str | None:
        match = CLAUSE_NUMBER_PATTERN.match(self.text)
        return match.group(1) if match else None
