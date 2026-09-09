"""Turns a fetched raw document (HTML or PDF bytes) into an ordered list of
structural `Block`s — headings, paragraphs, tables — that `ingestion.chunking`
groups into clause-aware chunks. Kept separate from chunking so a new source
format (Step 7's Bhashini transcripts, say) only needs a new parser, not a
new chunker.
"""
