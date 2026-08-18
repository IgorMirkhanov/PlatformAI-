"""Channel connector contract + string-key registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, TypeVar

from loguru import logger

from app.schemas.omnichannel.message import InboundMessage, OutboundMessage

ConnectorCls = TypeVar("ConnectorCls", bound=type["BaseChannelConnector"])


class ChannelConnectorError(Exception):
    """Base error for Omnichannel connectors (never leak vendor SDK types upward)."""

    def __init__(
        self,
        message: str,
        *,
        channel: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.channel = channel
        self.cause = cause


class UnknownChannelError(ChannelConnectorError):
    def __init__(self, channel: str) -> None:
        known = ", ".join(ChannelRegistry.available()) or "(none)"
        super().__init__(
            f"Unknown Omnichannel connector '{channel}'. Registered: {known}.",
            channel=channel,
        )


class BaseChannelConnector(ABC):
    """
    Adapter contract for messengers / widgets.

    CRM, automations, and Flow Builder depend only on InboundMessage /
    OutboundMessage — never on WhatsApp / Telegram / webchat SDKs.
    """

    channel_id: str = "base"

    @abstractmethod
    async def send_message(self, message: OutboundMessage) -> bool:
        """Deliver an outbound message. Return True on success."""

    @abstractmethod
    async def parse_webhook(self, raw_data: dict[str, Any]) -> InboundMessage:
        """Map vendor webhook JSON → normalized InboundMessage."""


class ChannelRegistry:
    """
    Resolve connectors by string id (``whatsapp``, ``telegram``, ``web_chat``).

    New adapters register via ``@ChannelRegistry.register("id")`` without
    editing registry internals.
    """

    _registry: dict[str, type[BaseChannelConnector]] = {}

    @classmethod
    def register(cls, channel_id: str) -> Callable[[ConnectorCls], ConnectorCls]:
        key = channel_id.strip().lower()

        def decorator(connector_cls: ConnectorCls) -> ConnectorCls:
            cls._registry[key] = connector_cls
            connector_cls.channel_id = key  # type: ignore[attr-defined]
            return connector_cls

        return decorator

    @classmethod
    def available(cls) -> list[str]:
        return sorted(cls._registry.keys())

    @classmethod
    def create(cls, channel_id: str, **kwargs: Any) -> BaseChannelConnector:
        key = (channel_id or "").strip().lower()
        connector_cls = cls._registry.get(key)
        if connector_cls is None:
            raise UnknownChannelError(key or channel_id)
        instance = connector_cls(**kwargs)
        logger.debug(
            "ChannelRegistry.created | channel={channel} class={cls}",
            channel=key,
            cls=connector_cls.__name__,
        )
        return instance

    @classmethod
    def get(cls, channel_id: str) -> type[BaseChannelConnector]:
        key = (channel_id or "").strip().lower()
        connector_cls = cls._registry.get(key)
        if connector_cls is None:
            raise UnknownChannelError(key or channel_id)
        return connector_cls


def get_channel_connector(channel_id: str, **kwargs: Any) -> BaseChannelConnector:
    """Convenience factory entry-point for call sites."""
    # Side-effect import registers built-in connectors (whatsapp, …).
    import app.services.omnichannel.connectors  # noqa: F401

    return ChannelRegistry.create(channel_id, **kwargs)
