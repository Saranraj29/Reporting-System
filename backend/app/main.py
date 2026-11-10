import logging
import time
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import get_settings
from .db import get_engine, session_scope
from .errors import install_error_handlers
from .routers import ai_admin, ai_reports, assistant, auth, dashboard, people, reports, setup, tasks, timeoff
from .services import mail
from .services.tenancy import sync_permissions

log = logging.getLogger("api")
API = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    get_settings()  # fails fast on insecure production config
    with session_scope() as db:
        sync_permissions(db)  # the permission list is owned by code
    yield


def create_app() -> FastAPI:
    s = get_settings()
    for problem in mail.config_problems():  # a mail setup that cannot work is said out loud at start-up, not found by a user who never got an email
        logging.getLogger("mail").warning("email configuration: %s", problem)
    app = FastAPI(title="Project Transparency Platform", version="1.0.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.add_middleware(
        CORSMiddleware, allow_origins=[s.web_origin], allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"],
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def write_log(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        if request.method != "GET":  # every write is logged with user id and company id (audit-log hook)
            log.info(
                "write %s %s -> %s user=%s company=%s %.0fms", request.method, request.url.path, response.status_code,
                getattr(request.state, "user_id", "-"), getattr(request.state, "company_id", "-"),
                (time.perf_counter() - start) * 1000,
            )
        return response

    api = APIRouter(prefix=API)
    for r in (auth.router, people.router, setup.router, tasks.router, dashboard.router, reports.router, reports.shared_router, ai_reports.router, ai_admin.router, assistant.router, timeoff.router):
        api.include_router(r)
    app.include_router(api)

    @app.get("/health", tags=["health"])
    @app.get(f"{API}/health", tags=["health"], include_in_schema=False)
    def health():
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app


app = create_app()
