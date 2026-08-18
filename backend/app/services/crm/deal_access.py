"""CRM deal access helpers — global vs per-deal operator scoping."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models.core_models import UserRole
from app.models.crm.deal import CrmDeal
from app.models.users import User

# Roles that see every deal inside the tenant (SPEC §7.1).
CRM_GLOBAL_DEAL_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.OWNER, UserRole.ADMIN}
)

# Roles allowed to read/create/move CRM deals (PROMPT_ENGINEER has no CRM access).
CRM_DEAL_ACCESS_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.OWNER, UserRole.ADMIN, UserRole.OPERATOR}
)

# Roles allowed to delete deals / manage CRM admin surfaces.
CRM_DEAL_ADMIN_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.OWNER, UserRole.ADMIN}
)


@dataclass(frozen=True, slots=True)
class CrmActor:
    """Authenticated CRM caller used for deal visibility / mutation checks."""

    user_id: uuid.UUID
    role: UserRole

    @classmethod
    def from_user(cls, user: User) -> CrmActor:
        role = getattr(user, "role", None) or UserRole.OPERATOR
        return cls(user_id=uuid.UUID(str(user.id)), role=role)

    @property
    def sees_all_deals(self) -> bool:
        return self.role in CRM_GLOBAL_DEAL_ROLES

    def can_view_deal(self, deal: CrmDeal) -> bool:
        if self.sees_all_deals:
            return True
        assigned = getattr(deal, "assigned_user_id", None)
        return assigned is None or assigned == self.user_id

    def can_mutate_deal(self, deal: CrmDeal) -> bool:
        """Operators may mutate unassigned deals or deals assigned to themselves."""
        return self.can_view_deal(deal)
