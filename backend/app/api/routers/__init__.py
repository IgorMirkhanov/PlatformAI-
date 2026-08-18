"""SaaS ``api/routers`` package — preferred layout for new modules.



Existing production routes live under ``api/endpoints``; new auth extensions

and tenant-aware examples are mounted from here without breaking tokenUrl.

"""



from app.api.routers.auth import router as auth_extensions_router

from app.api.routers.bots import router as saas_bots_router



__all__ = [

    "auth_extensions_router",

    "saas_bots_router",

]


