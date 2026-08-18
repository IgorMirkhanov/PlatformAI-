"""Omnichannel services — connectors, registry, message log."""

from app.services.omnichannel.base_connector import (
    BaseChannelConnector,
    ChannelConnectorError,
    ChannelRegistry,
    UnknownChannelError,
    get_channel_connector,
)
from app.services.omnichannel.message_log_service import (
    MessageLogService,
    message_log_service,
)

# Register built-in connectors (whatsapp, …).
import app.services.omnichannel.connectors  # noqa: E402, F401

__all__ = [
    "BaseChannelConnector",
    "ChannelConnectorError",
    "ChannelRegistry",
    "MessageLogService",
    "UnknownChannelError",
    "get_channel_connector",
    "message_log_service",
]
