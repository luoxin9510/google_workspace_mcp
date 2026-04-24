"""Markdown to Google Docs API batchUpdate request converter.

Parses CommonMark+GFM markdown and emits a list of Docs API request dicts
that, when applied in order, render the markdown into a document or a
specific tab within a document.

Primary entry point - markdown_to_docs_requests(markdown_text, tab_id=None).
"""

from __future__ import annotations

from typing import Optional

from markdown_it import MarkdownIt


def markdown_to_docs_requests(
    markdown_text: str,
    tab_id: Optional[str] = None,
    start_index: int = 1,
) -> list[dict]:
    """Convert markdown to a list of Docs API batchUpdate request dicts.

    Args:
        markdown_text - the markdown source
        tab_id - optional tab ID; when provided, every range targets this tab
        start_index - document index at which content insertion begins

    Returns:
        Ordered list of request dicts. Empty list for empty input.
    """
    if not markdown_text.strip():
        return []

    md = MarkdownIt("commonmark")
    tokens = md.parse(markdown_text)

    requests: list[dict] = []
    _emit_requests(tokens, requests, tab_id, start_index)
    return requests


def _emit_requests(tokens, requests, tab_id, start_index):
    """Walk markdown-it tokens and append Docs API requests. Stub - to be filled in Task 5."""
    pass
