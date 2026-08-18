"""Backward-compatible chunking API.

Canonical implementation lives in ``document_parser.RecursiveCharacterTextSplitter``.
"""

from __future__ import annotations

from app.services.document_parser import split_text_into_chunks

__all__ = ["split_text_into_chunks"]
