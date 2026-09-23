"""Telas da aplicacao."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
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


class NaoEncontrado(HTTPException):
    def __init__(self, detalhe: str = "Página não encontrada.") -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, detalhe)


def _render(request: Request, nome: str, **contexto) -> HTMLResponse:
    return templates.TemplateResponse(request, nome, {**BASE, **contexto})


def _voltar(destino: str) -> RedirectResponse:
    return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)


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

    from app.models import Questao, RecorteQuestao

    ids = {q.numero: q.id for q in s.scalars(select(Questao).where(Questao.prova_id == prova.id))}
    for estatistica in quadro.questoes:
        estatistica.id = ids.get(estatistica.numero)
    recortes = {
        r.questao_id: r
        for r in s.scalars(
            select(RecorteQuestao).where(RecorteQuestao.questao_id.in_(list(ids.values())))
        )
    }
    com_enunciado = set(recortes)
    com_apoio = {ident for ident, r in recortes.items() if r.apoio}

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
        com_enunciado=com_enunciado,
        com_apoio=com_apoio,
    )


# ── alunos ──────────────────────────────────────────────────────────────────────

@router.get("/alunos", response_class=HTMLResponse)
def alunos(
    request: Request,
    aviso: str | None = None,
    usuario: Usuario = Depends(auth.exigir_admin),
    escopo: auth.Escopo = Depends(auth.escopo),
    s: Session = Depends(auth.obter_sessao),
):
    from app.models import Aluno, Falta, ResultadoProva

    provas_por_aluno = dict(
        s.execute(
            select(ResultadoProva.aluno_id, func.count()).group_by(ResultadoProva.aluno_id)
        ).all()
    )
    faltas_por_aluno = dict(
        s.execute(
            select(Falta.aluno_id, func.count())
            .where(Falta.confirmada.is_(True))
            .group_by(Falta.aluno_id)
        ).all()
    )

    def montar(aluno):
        return {
            "id": aluno.id,
            "nome": aluno.nome_canonico,
            "rm": aluno.rm,
            "no_roster": aluno.no_roster,
            "provas": provas_por_aluno.get(aluno.id, 0),
            "faltas": faltas_por_aluno.get(aluno.id, 0),
        }

    todos = list(s.scalars(select(Aluno).order_by(Aluno.nome_canonico)))
    return _render(
        request,
        "alunos.html",
        pagina="alunos",
        usuario=usuario,
        escopo=escopo,
        aviso=aviso,
        ativos=[montar(a) for a in todos if a.ativo],
        inativos=[montar(a) for a in todos if not a.ativo],
    )


@router.post("/alunos/{aluno_id}/remover", include_in_schema=False)
def remover_aluno(
    aluno_id: int,
    usuario: Usuario = Depends(auth.exigir_admin),
    s: Session = Depends(auth.obter_sessao),
):
    from app.models import Aluno

    aluno = s.get(Aluno, aluno_id)
    if aluno is None:
        raise NaoEncontrado("Aluno não encontrado.")
    aluno.ativo = False
    return _voltar(f"/alunos?aviso={aluno.nome_canonico} saiu da turma. Os lançamentos ficaram guardados.")


@router.post("/alunos/{aluno_id}/devolver", include_in_schema=False)
def devolver_aluno(
    aluno_id: int,
    usuario: Usuario = Depends(auth.exigir_admin),
    s: Session = Depends(auth.obter_sessao),
):
    from app.models import Aluno

    aluno = s.get(Aluno, aluno_id)
    if aluno is None:
        raise NaoEncontrado("Aluno não encontrado.")
    aluno.ativo = True
    return _voltar(f"/alunos?aviso={aluno.nome_canonico} voltou para a turma.")


# ── faltas ──────────────────────────────────────────────────────────────────────

@router.get("/faltas", response_class=HTMLResponse)
def faltas(
    request: Request,
    fase: str | None = None,
    materia: str | None = None,
    situacao: str = "pendentes",
    aviso: str | None = None,
    usuario: Usuario = Depends(auth.exigir_admin),
    escopo: auth.Escopo = Depends(auth.escopo),
    s: Session = Depends(auth.obter_sessao),
):
    from app.models import Aluno, Falta, ResultadoProva

    alvo_fase = Fase(fase) if fase in {f.value for f in Fase} else Fase.SEGUNDA
    alvo_materia = materia if materia in {m.value for m in Materia} else Materia.QUIMICA.value

    total = s.query(Falta).count()
    pendentes = s.query(Falta).filter(Falta.confirmada.is_(None)).count()
    confirmadas = s.query(Falta).filter(Falta.confirmada.is_(True)).count()

    provas = list(
        s.scalars(
            select(Prova)
            .where(Prova.fase == alvo_fase, Prova.materia == Materia(alvo_materia))
            .order_by(Prova.ciclo)
        )
    )
    nomes = {a.id: a.nome_canonico for a in s.scalars(select(Aluno))}
    grupos = []

    for prova in provas:
        registros = list(s.scalars(select(Falta).where(Falta.prova_id == prova.id)))
        if situacao == "pendentes":
            registros = [f for f in registros if f.confirmada is None]
        if not registros:
            continue
        notas = {
            r.aluno_id: r.nota
            for r in s.scalars(select(ResultadoProva).where(ResultadoProva.prova_id == prova.id))
        }
        quadro = M.desempenho(s, prova)
        grupos.append(
            {
                "ciclo": prova.ciclo,
                "fase": prova.fase.value,
                "materia": prova.materia.value,
                "presentes": len(quadro.presentes),
                "total": quadro.total_matriculados,
                "media": quadro.media,
                "pendentes": sum(1 for f in registros if f.confirmada is None),
                "faltas": sorted(
                    (
                        {
                            "id": f.id,
                            "nome": nomes.get(f.aluno_id, "?"),
                            "nota": notas.get(f.aluno_id),
                            "confirmada": f.confirmada,
                        }
                        for f in registros
                    ),
                    key=lambda x: x["nome"],
                ),
            }
        )

    volta = f"/faltas?fase={alvo_fase.value}&materia={alvo_materia}&situacao={situacao}"
    return _render(
        request,
        "faltas.html",
        pagina="faltas",
        usuario=usuario,
        escopo=escopo,
        aviso=aviso,
        grupos=grupos,
        pendentes=pendentes,
        confirmadas=confirmadas,
        descartadas=total - pendentes - confirmadas,
        fases=[f.value for f in Fase],
        materias=[m.value for m in Materia],
        fase_atual=alvo_fase.value,
        materia_atual=alvo_materia,
        situacao=situacao,
        volta=volta,
    )


@router.post("/faltas/{falta_id}", include_in_schema=False)
def decidir_falta(
    falta_id: int,
    decisao: str = Form(...),
    volta: str = Form("/faltas"),
    usuario: Usuario = Depends(auth.exigir_admin),
    s: Session = Depends(auth.obter_sessao),
):
    from app.models import Falta

    falta = s.get(Falta, falta_id)
    if falta is None:
        raise NaoEncontrado("Falta não encontrada.")
    falta.confirmada = decisao == "faltou"
    return _voltar(volta)


# ── provas em PDF e recortes ────────────────────────────────────────────────────

@router.get("/arquivos", response_class=HTMLResponse)
def arquivos(
    request: Request,
    aviso: str | None = None,
    usuario: Usuario = Depends(auth.exigir_admin),
    escopo: auth.Escopo = Depends(auth.escopo),
    s: Session = Depends(auth.obter_sessao),
):
    from app.models import ArquivoProva, Questao, RecorteQuestao

    provas = list(s.scalars(select(Prova).order_by(Prova.ciclo, Prova.fase, Prova.materia)))
    arquivos_por_prova = {a.prova_id: a for a in s.scalars(select(ArquivoProva))}
    recortes = {
        r.questao_id: r for r in s.scalars(select(RecorteQuestao))
    }

    linhas = []
    for prova in provas:
        questoes = list(s.scalars(select(Questao).where(Questao.prova_id == prova.id)))
        com_recorte = sum(1 for q in questoes if q.id in recortes)
        revisados = sum(1 for q in questoes if q.id in recortes and recortes[q.id].revisado)
        linhas.append(
            {
                "id": prova.id,
                "ciclo": prova.ciclo,
                "fase": prova.fase.value,
                "materia": prova.materia.value,
                "questoes": len(questoes),
                "recortes": com_recorte,
                "revisados": revisados,
                "arquivo": arquivos_por_prova.get(prova.id),
            }
        )

    return _render(
        request, "arquivos.html", pagina="arquivos", usuario=usuario,
        escopo=escopo, aviso=aviso, linhas=linhas,
    )


@router.post("/arquivos/{prova_id}", include_in_schema=False)
async def enviar_prova(
    prova_id: int,
    request: Request,
    usuario: Usuario = Depends(auth.exigir_admin),
    s: Session = Depends(auth.obter_sessao),
):
    from app.provas import servico

    prova = s.get(Prova, prova_id)
    if prova is None:
        raise NaoEncontrado("Prova não encontrada.")

    formulario = await request.form()
    enviado = formulario.get("pdf")
    if enviado is None or not getattr(enviado, "filename", ""):
        return _voltar("/arquivos?aviso=Escolha um arquivo PDF.")

    dados = await enviado.read()
    if not dados.startswith(b"%PDF"):
        return _voltar(f"/arquivos?aviso={enviado.filename} não é um PDF.")

    registro = servico.guardar_pdf(s, prova, enviado.filename, dados)
    resumo = servico.segmentar(s, prova, registro)
    servico.limpar_cache(prova.id)

    recado = (
        f"{prova.materia.value} · Ciclo {prova.ciclo}: {resumo.casadas} de "
        f"{resumo.questoes_da_prova} questões localizadas no PDF"
    )
    if not resumo.completo:
        recado += " — confira os recortes antes de usar"
    return _voltar(f"/arquivos?aviso={recado}")


@router.get("/questoes/{questao_id}/imagem", include_in_schema=False)
def imagem_da_questao(
    questao_id: int,
    apoio: bool = False,
    usuario: Usuario = Depends(auth.exigir_login),
    escopo: auth.Escopo = Depends(auth.escopo),
    s: Session = Depends(auth.obter_sessao),
):
    from fastapi.responses import FileResponse

    from app.models import Questao
    from app.provas import servico

    questao = s.get(Questao, questao_id)
    if questao is None:
        raise NaoEncontrado("Questão não encontrada.")
    escopo.exigir(questao.prova.materia)

    imagem = servico.imagem_da_questao(s, questao, com_apoio=apoio)
    if imagem is None:
        raise NaoEncontrado("O enunciado desta questão ainda não foi enviado.")
    return FileResponse(imagem.caminho, media_type="image/png")
