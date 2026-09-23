"""Ponto de entrada da aplicacao."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.config import config


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


@app.get("/saude")
def saude() -> dict[str, str]:
    return {"status": "ok", "ambiente": config.ambiente}


@app.get("/", response_class=HTMLResponse)
def inicio() -> str:
    return (
        "<!doctype html><html lang=\'pt-BR\'><meta charset=\'utf-8\'>"
        "<title>Análise de Simulados</title>"
        "<h1>Análise de Simulados — Turma ITA 2026</h1>"
        "<p>Ambiente preparado. As telas entram na próxima etapa.</p>"
    )
