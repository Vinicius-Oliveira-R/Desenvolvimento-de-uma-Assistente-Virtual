from fastapi import FastAPI

from app.core.config import get_settings
from app.core.database import Base, engine
from app.routers.assistant import router as assistant_router
from app.routers.auth import router as auth_router
from app.routers.consultas import router as consultas_router
from app.routers.horarios import router as horarios_router
from app.routers.medicos import router as medicos_router
from app.routers.pacientes import router as pacientes_router

settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)

Base.metadata.create_all(bind=engine)

app.include_router(auth_router)
app.include_router(pacientes_router)
app.include_router(medicos_router)
app.include_router(horarios_router)
app.include_router(consultas_router)
app.include_router(assistant_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "Assistente Clínico API"}
