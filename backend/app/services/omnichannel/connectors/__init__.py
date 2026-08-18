"""Built-in Omnichannel channel connectors (side-effect registration)."""

from app.services.omnichannel.connectors.telegram_connector import TelegramConnector
from app.services.omnichannel.connectors.whatsapp_connector import WhatsAppConnector

__all__ = ["TelegramConnector", "WhatsAppConnector"]
