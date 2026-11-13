from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.backend.core.config import get_settings
from app.backend.core.database import Base, engine
from app.backend.core.exceptions import DomainError
from app.backend.routers.assistant import router as assistant_router
from app.backend.routers.auth import router as auth_router
from app.backend.routers.cadastros import router as cadastros_router
from app.backend.routers.consultas import router as consultas_router
from app.backend.routers.horarios import router as horarios_router
from app.backend.routers.medicos import router as medicos_router
from app.backend.routers.notificacoes import router as notificacoes_router
from app.backend.routers.pacientes import router as pacientes_router

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    from sqlalchemy import inspect
    for table, required in (("usuarios", {"ativo", "token_version"}), ("medicos", {"ativo"})):
        present = {column["name"] for column in inspect(engine).get_columns(table)}
        if not required <= present:
            raise RuntimeError("Schema anterior à auditoria; execute python -m app.backend.migrate --apply antes de iniciar")
    yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DomainError)
async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


ROUTERS = (
    auth_router,
    cadastros_router,
    pacientes_router,
    medicos_router,
    horarios_router,
    consultas_router,
    notificacoes_router,
    assistant_router,
)
for router in ROUTERS:
    app.include_router(router, prefix=settings.api_prefix)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "Assistente Clínico API"}
