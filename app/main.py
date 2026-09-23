"""Ponto de entrada da aplicacao."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.auth import NaoAutenticado
from app.config import RAIZ, config
from app.routers import web


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    config.preparar_pastas()
    yield


app = FastAPI(
    title="Análise de Simulados — Turma ITA 2026",
    lifespan=ciclo_de_vida,
    docs_url="/docs" if config.desenvolvimento else None,
    redoc_url=None,
)

app.mount("/static", StaticFiles(directory=str(RAIZ / "app" / "static")), name="static")
app.include_router(web.router)


@app.exception_handler(NaoAutenticado)
async def sem_sessao(request: Request, exc: NaoAutenticado):
    """Quem nao esta logado vai para a tela de login, nao para um erro cru."""
    return RedirectResponse("/entrar", status_code=303)


@app.get("/saude", include_in_schema=False)
def saude() -> dict[str, str]:
    return {"status": "ok", "ambiente": config.ambiente}
