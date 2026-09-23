"""Ponto de entrada da aplicacao."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
# A Starlette levanta a exceção DELA para rota não casada, e a do FastAPI herda
# dessa. Registrar na classe base cobre os dois casos.
from starlette.exceptions import HTTPException

from app.auth import NaoAutenticado, usuario_da_requisicao
from app.config import RAIZ, config
from app.db import Sessao
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
    """Quem nao esta logado vai para o login, nao para um erro cru."""
    return RedirectResponse("/entrar", status_code=303)


TITULOS = {
    403: "Sem acesso a esta área",
    404: "Página não encontrada",
    405: "Página não encontrada",
}


@app.exception_handler(HTTPException)
async def erro_em_pagina(request: Request, exc: HTTPException):
    """Erros de navegação viram página; só a API responde JSON."""
    aceita_html = "text/html" in request.headers.get("accept", "")
    if not aceita_html or exc.status_code not in TITULOS:
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    s = Sessao()
    try:
        usuario = usuario_da_requisicao(request, s)
        if usuario is None:
            return RedirectResponse("/entrar", status_code=303)
        from app.auth import Escopo

        return web.templates.TemplateResponse(
            request,
            "erro.html",
            {
                **web.BASE,
                "pagina": "",
                "usuario": usuario,
                "escopo": Escopo(usuario),
                "titulo": TITULOS[exc.status_code],
                "mensagem": exc.detail,
            },
            status_code=exc.status_code,
        )
    finally:
        s.close()


@app.get("/saude", include_in_schema=False)
def saude() -> dict[str, str]:
    return {"status": "ok", "ambiente": config.ambiente}
