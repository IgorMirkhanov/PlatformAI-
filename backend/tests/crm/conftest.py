"""CRM test defaults — disable plan quotas unless a test opts in."""

from __future__ import annotations

from typing import Any

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "crm_quotas: exercise real CRM plan-quota enforcement (do not stub asserts)",
    )


@pytest.fixture(autouse=True)
def _passthrough_crm_quotas(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Existing CRM unit tests use in-memory fakes without plan/Stripe rows.
    Skip CRM quota asserts unless the test is marked ``crm_quotas``.
    """
    if request.node.get_closest_marker("crm_quotas"):
        return

    async def _ok(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        "app.services.quota_service.quota_service.assert_crm_contacts_quota",
        _ok,
    )
    monkeypatch.setattr(
        "app.services.quota_service.quota_service.assert_crm_deals_open_quota",
        _ok,
    )
    monkeypatch.setattr(
        "app.services.quota_service.quota_service.assert_crm_automation_rules_quota",
        _ok,
    )
