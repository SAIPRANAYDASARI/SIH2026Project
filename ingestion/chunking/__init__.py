"""Groups parsed `Block`s into clause-aware chunks: 400-800 tokens, ~15%
overlap between consecutive chunks, never splitting a table or a numbered
clause across chunk boundaries. See `chunker.py` for the algorithm and
`docs/DECISIONS.md` for the token-counting approximation used.
"""
