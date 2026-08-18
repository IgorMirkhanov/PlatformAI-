"""Admin Panel HTTP API (support search + impersonation).

Implementation lives in ``app.api.endpoints.admin`` (modular routers). Mount point:
``/api/v1/admin/*`` via ``app.api.endpoints.admin.router``.

Key routes:
  - GET  /api/v1/admin/users/search?query=
  - POST /api/v1/admin/impersonate
"""

from app.api.endpoints.admin import router

__all__ = ["router"]
