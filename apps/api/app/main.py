"""FastAPI 入口。业务路由挂在 /api 下并要求登录；健康检查不要求登录。"""

from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from sqlalchemy import text

from app.core.auth import bootstrap_operator, current_operator
from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.core.routes import router as core_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_settings()
    with get_sessionmaker()() as db:
        bootstrap_operator(db)
    yield


app = FastAPI(
    title="Beacon API", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json"
)
api = APIRouter(prefix="/api")


@app.middleware("http")
async def places_no_store(request: Request, call_next):
    response = await call_next(request)
    if "/google-places" in request.url.path:
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
    return response


@api.get("/health")
def health() -> dict:
    return {"status": "ok"}


@api.get("/health/db")
def health_db() -> dict:
    with get_engine().connect() as conn:
        conn.execute(text("select 1"))
    return {"status": "ok", "database": "reachable"}


api.include_router(core_router)
protected = APIRouter(prefix="/api", dependencies=[Depends(current_operator)])
from app.modules.content.routes import router as content_router  # noqa: E402
from app.modules.leads.google_places import router as google_places_router  # noqa: E402
from app.modules.leads.routes import router as leads_router  # noqa: E402
from app.modules.leads.website_search import router as website_search_router  # noqa: E402
from app.modules.menus.routes import router as menus_router  # noqa: E402
from app.modules.sales.routes import router as sales_router  # noqa: E402

protected.include_router(leads_router)
protected.include_router(website_search_router)
protected.include_router(google_places_router)
protected.include_router(menus_router)
protected.include_router(content_router)
protected.include_router(sales_router)


def include_module_routers() -> None:
    app.include_router(api)
    app.include_router(protected)


include_module_routers()
