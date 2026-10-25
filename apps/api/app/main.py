"""FastAPI 入口。业务路由挂在 /api 下并要求登录；健康检查不要求登录。"""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.auth import bootstrap_operator, current_operator
from app.core.avatars import router as avatars_router
from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.core.routes import router as core_router
from app.core.users import router as users_router


class OAuthAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn 默认日志包含 OAuth 授权码查询参数，仅记录回调路径。
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            path = record.args[2]
            if isinstance(path, str) and path.startswith(
                ("/api/gmail/oauth/callback", "/api/outreach/oauth/callback", "/api/outreach/webhook")
            ):
                args = list(record.args)
                args[2] = path.split("?", 1)[0]
                record.args = tuple(args)
        return True


logging.getLogger("uvicorn.access").addFilter(OAuthAccessFilter())


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_settings()
    with get_sessionmaker()() as db:
        bootstrap_operator(db)
    from app.modules.leads.worker import run

    stop = threading.Event()
    worker = None
    if get_settings().workflow_worker_enabled:
        worker = threading.Thread(target=run, args=(stop,), daemon=True, name="list-workflows")
        worker.start()
    try:
        yield
    finally:
        stop.set()
        if worker:
            worker.join(timeout=5)


app = FastAPI(
    title="Beacon API", version="0.1.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json"
)
api = APIRouter(prefix="/api")


@app.middleware("http")
async def places_no_store(request: Request, call_next):
    response = await call_next(request)
    if (
        request.url.path.startswith(
            (
                "/api/auth",
                "/api/users",
                "/api/leads",
                "/api/batches",
                "/api/tasks",
                "/api/files",
                "/api/communication",
                "/api/assignment",
            )
        )
        or "/google-places" in request.url.path
        or "/maps-menu" in request.url.path
        or "/gmail" in request.url.path
        or "/outreach" in request.url.path
    ):
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
    return response


@api.get("/health")
def health() -> dict:
    result = {"status": "ok"}
    release = get_settings().release_sha
    if release:
        result["release"] = release
    return result


@api.get("/health/db")
def health_db() -> dict:
    with get_engine().connect() as conn:
        conn.execute(text("select 1"))
    return {"status": "ok", "database": "reachable"}


api.include_router(core_router)
protected = APIRouter(prefix="/api", dependencies=[Depends(current_operator)])
from app.modules.content.routes import router as content_router  # noqa: E402
from app.modules.directory.routes import router as directory_router  # noqa: E402
from app.modules.gmail.routes import callback_router as gmail_callback_router  # noqa: E402
from app.modules.gmail.routes import router as gmail_router  # noqa: E402
from app.modules.leads.auto_research import router as auto_research_router  # noqa: E402
from app.modules.leads.google_places import router as google_places_router  # noqa: E402
from app.modules.leads.routes import router as leads_router  # noqa: E402
from app.modules.leads.website_search import router as website_search_router  # noqa: E402
from app.modules.menus.maps import router as maps_menu_router  # noqa: E402
from app.modules.menus.maps import worker_router as maps_worker_router  # noqa: E402
from app.modules.menus.routes import router as menus_router  # noqa: E402
from app.modules.outreach.routes import public_router as outreach_public_router  # noqa: E402
from app.modules.outreach.routes import router as outreach_router  # noqa: E402
from app.modules.sales.routes import router as sales_router  # noqa: E402

protected.include_router(users_router)
protected.include_router(avatars_router)
protected.include_router(outreach_router)
protected.include_router(gmail_router)
from app.modules.leads.policy import router as policy_router  # noqa: E402

protected.include_router(policy_router)
from app.modules.leads.assignment import router as assignment_router  # noqa: E402

protected.include_router(assignment_router)
from app.modules.leads.enrichment import router as enrichment_router  # noqa: E402

protected.include_router(enrichment_router)
protected.include_router(leads_router)
protected.include_router(directory_router)
protected.include_router(auto_research_router)
protected.include_router(website_search_router)
protected.include_router(google_places_router)
protected.include_router(menus_router)
protected.include_router(maps_menu_router)
protected.include_router(content_router)
from app.modules.sales.workbench import router as communication_router  # noqa: E402

protected.include_router(communication_router)
from app.modules.sales.assistance import router as assistance_router  # noqa: E402

protected.include_router(assistance_router)
protected.include_router(sales_router)


def include_module_routers() -> None:
    app.include_router(api)
    app.include_router(protected)
    app.include_router(maps_worker_router)
    app.include_router(gmail_callback_router)
    app.include_router(outreach_public_router)


include_module_routers()


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith(
        (
            "/api/auth",
            "/api/users",
            "/api/leads",
            "/api/batches",
            "/api/tasks",
            "/api/files",
            "/api/communication",
            "/api/assignment",
        )
    ):
        return JSONResponse(
            status_code=422, content={"detail": "账号信息格式无效：请检查字段；新密码或临时密码需为 8～128 个字符"}
        )
    if request.url.path.startswith("/api/outreach"):
        return JSONResponse(status_code=422, content={"detail": "配置格式无效，请核对字段及账号类型"})
    from fastapi.exception_handlers import request_validation_exception_handler

    return await request_validation_exception_handler(request, exc)
