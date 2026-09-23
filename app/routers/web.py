"""Telas da aplicacao."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth
from app.analytics import metrics as M
from app.analytics import rules as R
from app.config import RAIZ, config
from app.models import Fase, Materia, Prova, Usuario

router = APIRouter()
templates = Jinja2Templates(directory=str(RAIZ / "app" / "templates"))


def classe_nota(nota: float, maxima: float) -> str:
    """Faixa de cor da celula na 2ª fase. O numero fica visivel em todas."""
    if nota >= maxima:
        return "total"
    if nota >= maxima / 2:
        return "parcial"
    if nota > 0:
        return "fraco"
    return "zero"


BASE = {
    "fmt": R.formatar,
    "fmt_sinal": R.formatar_sinal,
    "fmt_pct": R.formatar_percentual,
    "classe_nota": classe_nota,
    "corte": config.corte_materia,
}


def _render(request: Request, nome: str, **contexto) -> HTMLResponse:
    return templates.TemplateResponse(request, nome, {**BASE, **contexto})


# ── login ───────────────────────────────────────────────────────────────────────

@router.get("/", include_in_schema=False)
def raiz(request: Request, s: Session = Depends(auth.obter_sessao)):
    destino = "/painel" if auth.usuario_da_requisicao(request, s) else "/entrar"
    return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/entrar", response_class=HTMLResponse)
def tela_login(request: Request, s: Session = Depends(auth.obter_sessao)):
    if auth.usuario_da_requisicao(request, s):
        return RedirectResponse("/painel", status_code=status.HTTP_303_SEE_OTHER)
    return _render(request, "login.html")


@router.post("/entrar", response_class=HTMLResponse)
def entrar(
    request: Request,
    email: str = Form(...),
    senha: str = Form(...),
    s: Session = Depends(auth.obter_sessao),
):
    usuario = auth.autenticar(s, email, senha)
    if usuario is None:
        return _render(
            request, "login.html", erro="E-mail ou senha incorretos.", email=email
        )
    resposta = RedirectResponse("/painel", status_code=status.HTTP_303_SEE_OTHER)
    auth.abrir_sessao(resposta, usuario)
    return resposta


@router.get("/sair", include_in_schema=False)
def sair():
    resposta = RedirectResponse("/entrar", status_code=status.HTTP_303_SEE_OTHER)
    auth.fechar_sessao(resposta)
    return resposta


# ── painel ──────────────────────────────────────────────────────────────────────

def _ciclos(s: Session) -> list[int]:
    return sorted({c for (c,) in s.execute(select(Prova.ciclo).distinct())})


@router.get("/painel", response_class=HTMLResponse)
def painel(
    request: Request,
    usuario: Usuario = Depends(auth.exigir_login),
    escopo: auth.Escopo = Depends(auth.escopo),
    s: Session = Depends(auth.obter_sessao),
):
    ciclos = _ciclos(s)
    visiveis = escopo.materias()
    linhas = []

    for fase in Fase:
        for materia in visiveis:
            medias = []
            for ciclo in ciclos:
                prova = M.obter_prova(s, ciclo, fase, materia)
                medias.append(M.desempenho(s, prova).media if prova else None)
            if not any(m is not None for m in medias):
                continue
            reais = [m for m in medias if m is not None]
            variacao = (
                medias[-1] - medias[-2]
                if len(medias) >= 2 and medias[-1] is not None and medias[-2] is not None
                else None
            )
            linhas.append(
                type(
                    "Linha",
                    (),
                    {
                        "fase": fase.value,
                        "materia": materia.value,
                        "medias": medias,
                        "variacao": variacao,
                        "ultima": reais[-1] if reais else None,
                    },
                )
            )

    return _render(
        request,
        "painel.html",
        pagina="painel",
        usuario=usuario,
        escopo=escopo,
        ciclos=ciclos,
        linhas=linhas,
    )


# ── prova ───────────────────────────────────────────────────────────────────────

@router.get("/provas", response_class=HTMLResponse)
def provas(
    request: Request,
    ciclo: int | None = None,
    fase: str | None = None,
    materia: str | None = None,
    usuario: Usuario = Depends(auth.exigir_login),
    escopo: auth.Escopo = Depends(auth.escopo),
    s: Session = Depends(auth.obter_sessao),
):
    ciclos = _ciclos(s)
    if not ciclos:
        return _render(
            request, "painel.html", pagina="provas", usuario=usuario,
            escopo=escopo, ciclos=[], linhas=[],
        )

    visiveis = escopo.materias()
    alvo_ciclo = ciclo if ciclo in ciclos else ciclos[-1]
    alvo_fase = Fase(fase) if fase in {f.value for f in Fase} else Fase.PRIMEIRA

    # Materia pedida e fora do escopo: negar explicitamente. Trocar em silencio pela
    # materia do professor deixaria a URL dizendo uma coisa e a pagina mostrando outra.
    if materia and materia in {m.value for m in Materia}:
        escopo.exigir(materia)
        escolhida = materia
    else:
        escolhida = visiveis[0].value

    prova = M.obter_prova(s, alvo_ciclo, alvo_fase, escolhida)
    if prova is None:
        # A combinacao nao existe (ex.: Redacao so na 2ª fase). Cai na primeira valida.
        for candidata in visiveis:
            prova = M.obter_prova(s, alvo_ciclo, alvo_fase, candidata)
            if prova is not None:
                break
    if prova is None:
        return _render(
            request, "painel.html", pagina="provas", usuario=usuario,
            escopo=escopo, ciclos=ciclos, linhas=[],
        )

    quadro = M.desempenho(s, prova)
    variacao, media_anterior = M.variacao_entre_ciclos(s, prova.ciclo, prova.fase, prova.materia)

    # So oferece no seletor as materias que existem naquele ciclo e fase.
    disponiveis = [
        m.value for m in visiveis if M.obter_prova(s, alvo_ciclo, alvo_fase, m) is not None
    ]

    return _render(
        request,
        "prova.html",
        pagina="provas",
        usuario=usuario,
        escopo=escopo,
        quadro=quadro,
        objetiva=prova.objetiva,
        variacao=variacao,
        media_anterior=media_anterior,
        ciclos=ciclos,
        fases=[f.value for f in Fase],
        materias=disponiveis,
    )
