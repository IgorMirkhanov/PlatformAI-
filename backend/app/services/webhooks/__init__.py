"""Webhook parser package."""
from app.services.webhooks.parsers import parse_inbound, parse_greenapi, parse_telegram, parse_wazzup, parse_widget

__all__ = [
    "parse_inbound",
    "parse_greenapi",
    "parse_telegram",
    "parse_wazzup",
    "parse_widget",
]
