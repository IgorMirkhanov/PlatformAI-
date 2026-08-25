from app.services.integration_hub.adapters.amocrm import AmoCRMHubAdapter
from app.services.integration_hub.adapters.bitrix24 import Bitrix24HubAdapter
from app.services.integration_hub.adapters.kaspi import KaspiPayHubAdapter
from app.services.integration_hub.adapters.wazzup import WazzupHubAdapter
from app.services.integration_hub.adapters.whatsapp import WhatsAppHubAdapter
from app.services.integration_hub.types import ProviderAdapter

_ADAPTERS: dict[str, ProviderAdapter] = {
    "amocrm": AmoCRMHubAdapter(),
    "kommo": AmoCRMHubAdapter(),
    "bitrix24": Bitrix24HubAdapter(),
    "wazzup": WazzupHubAdapter(),
    "whatsapp": WhatsAppHubAdapter(),
    "greenapi": WhatsAppHubAdapter(),
    "kaspi_pay": KaspiPayHubAdapter(),
}


def get_hub_adapter(provider: str) -> ProviderAdapter:
    key = (provider or "").strip().lower()
    adapter = _ADAPTERS.get(key)
    if adapter is None:
        raise ValueError(f"Unsupported Integration Hub provider: {provider}")
    return adapter


__all__ = ["get_hub_adapter"]
