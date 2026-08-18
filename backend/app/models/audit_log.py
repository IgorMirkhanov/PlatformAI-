"""Audit log model alias for the Admin Panel package layout.

Canonical table: ``admin_audit_logs`` (see ``app.models.admin_audit.AdminAuditLog``).
"""

from app.models.admin_audit import AdminAuditLog as AuditLog

__all__ = ["AuditLog"]
