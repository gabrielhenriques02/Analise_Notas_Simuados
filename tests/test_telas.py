"""Telas: login, escopo por materia e conteudo das paginas."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.db import Sessao
from app.main import app
from app.models import Papel, Usuario
from tests.conftest import requer_planilha

ADMIN = ("coord.teste@madan.com.br", "senhaAdmin123")
PROF = ("prof.teste@madan.com.br", "senhaProf123")


@pytest.fixture(scope="module", autouse=True)
def contas():
    s = Sessao()
    criadas = []
    for email, senha, papel, materias in [
        (*ADMIN, Papel.ADMIN, None),
        (*PROF, Papel.PROFESSOR, ["QUÍMICA"]),
    ]:
        if not s.query(Usuario).filter(Usuario.email == email).first():
            usuario, _ = auth.criar_usuario(
                s, email=email, nome=email.split("@")[0], papel=papel,
                materias=materias, senha=senha,
            )
            criadas.append(usuario.id)
    s.commit()
    yield
    for ident in criadas:
        s.delete(s.get(Usuario, ident))
    s.commit()
    s.close()


def logar(credenciais) -> TestClient:
    c = TestClient(app)
    c.__enter__()
    resposta = c.post("/entrar", data={"email": credenciais[0], "senha": credenciais[1]})
    assert resposta.status_code == 200
    return c


# ── acesso ──────────────────────────────────────────────────────────────────────

def test_sem_login_vai_para_a_tela_de_entrada():
    with TestClient(app, follow_redirects=False) as c:
        for caminho in ("/", "/painel", "/provas"):
            resposta = c.get(caminho)
            assert resposta.status_code == 303
            assert resposta.headers["location"] == "/entrar"


def test_login_errado_nao_abre_sessao():
    with TestClient(app, follow_redirects=False) as c:
        resposta = c.post("/entrar", data={"email": ADMIN[0], "senha": "errada"})
        assert resposta.status_code == 200
        assert "incorretos" in resposta.text
        assert "sessao" not in resposta.cookies


def test_cookie_de_sessao_e_protegido():
    with TestClient(app, follow_redirects=False) as c:
        resposta = c.post("/entrar", data={"email": ADMIN[0], "senha": ADMIN[1]})
        cookie = resposta.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "lax" in cookie.lower()


def test_sair_encerra_a_sessao():
    c = logar(ADMIN)
    assert c.get("/painel").status_code == 200
    c.get("/sair")
    with TestClient(app, follow_redirects=False) as limpo:
        assert limpo.get("/painel").status_code == 303
    c.__exit__(None, None, None)


# ── escopo ──────────────────────────────────────────────────────────────────────

@requer_planilha
def test_professor_nao_acessa_outra_materia():
    """Nega explicitamente em vez de trocar em silencio pela materia dele.

    Regressao: a versao anterior devolvia 200 com os dados de Quimica numa URL que
    pedia Matematica — a pagina mostrava um numero e a URL dizia outro.
    """
    c = logar(PROF)
    resposta = c.get("/provas", params={"ciclo": 5, "fase": "1ª FASE", "materia": "MATEMÁTICA"})
    assert resposta.status_code == 403
    assert "não tem acesso" in resposta.json()["detail"]
    c.__exit__(None, None, None)


@requer_planilha
def test_professor_acessa_a_propria_materia():
    c = logar(PROF)
    resposta = c.get("/provas", params={"ciclo": 5, "fase": "1ª FASE", "materia": "QUÍMICA"})
    assert resposta.status_code == 200
    assert "Desempenho em QUÍMICA" in resposta.text
    c.__exit__(None, None, None)


@requer_planilha
def test_painel_do_professor_so_mostra_a_materia_dele():
    c = logar(PROF)
    texto = c.get("/painel").text
    assert "QUÍMICA" in texto
    assert "MATEMÁTICA" not in texto
    assert "/faltas" not in texto      # área só da coordenação
    c.__exit__(None, None, None)


@requer_planilha
def test_admin_ve_todas_as_materias():
    c = logar(ADMIN)
    texto = c.get("/painel").text
    for materia in ("MATEMÁTICA", "FÍSICA", "QUÍMICA"):
        assert materia in texto
    assert "/faltas" in texto
    c.__exit__(None, None, None)


# ── conteudo ────────────────────────────────────────────────────────────────────

@requer_planilha
def test_tela_da_1a_fase_traz_os_numeros_do_relatorio():
    c = logar(ADMIN)
    texto = c.get(
        "/provas", params={"ciclo": 5, "fase": "1ª FASE", "materia": "MATEMÁTICA"}
    ).text

    for esperado in ("5,61", "+0,90", "26/30", "8,67", "10,00", "87%"):
        assert esperado in texto, f"faltou {esperado}"
    assert "1 de nível fácil · 3 de nível médio" in texto
    assert "ausente, não realizou a prova" in texto
    c.__exit__(None, None, None)


@requer_planilha
def test_grade_nao_depende_so_da_cor():
    """Verde/vermelho some no daltonismo mais comum; o glifo é o canal de reserva."""
    c = logar(ADMIN)
    texto = c.get(
        "/provas", params={"ciclo": 5, "fase": "1ª FASE", "materia": "MATEMÁTICA"}
    ).text

    assert "✓" in texto and "✗" in texto
    assert 'title="Questão 1: acertou"' in texto or 'title="Questão 1: errou"' in texto
    c.__exit__(None, None, None)


@requer_planilha
def test_alerta_vem_sempre_com_rotulo():
    """Status nunca é só cor: CRÍTICA e ATENÇÃO aparecem escritos."""
    c = logar(ADMIN)
    texto = c.get(
        "/provas", params={"ciclo": 5, "fase": "1ª FASE", "materia": "MATEMÁTICA"}
    ).text
    assert "CRÍTICA" in texto and "ATENÇÃO" in texto
    c.__exit__(None, None, None)


@requer_planilha
def test_tela_da_2a_fase_mostra_a_distribuicao():
    c = logar(ADMIN)
    texto = c.get(
        "/provas", params={"ciclo": 5, "fase": "2ª FASE", "materia": "MATEMÁTICA"}
    ).text
    assert "prova discursiva" in texto
    assert "empilhada" in texto           # distribuição das correções
    assert "nota máxima" in texto
    c.__exit__(None, None, None)


@requer_planilha
def test_larguras_de_barra_sao_arredondadas():
    """Evita width: 46.666666666666664% no HTML."""
    import re

    c = logar(ADMIN)
    texto = c.get(
        "/provas", params={"ciclo": 5, "fase": "1ª FASE", "materia": "MATEMÁTICA"}
    ).text
    # so as barras de dado; larguras fixas de layout nao contam
    larguras = re.findall(r'class="barra-preenche[^"]*"[^>]*?width:\s*([0-9.]+)%', texto)
    assert larguras, "nenhuma barra encontrada"
    for largura in larguras:
        assert len(largura.split(".")[-1]) <= 1, f"largura sem arredondar: {largura}"
    c.__exit__(None, None, None)


# ── páginas que o menu promete ──────────────────────────────────────────────────

@requer_planilha
def test_todo_link_do_menu_abre():
    """Regressão: o menu anunciava /alunos e /faltas antes de as rotas existirem,
    e o clique caía num 404 com JSON cru."""
    import re

    c = logar(ADMIN)
    painel = c.get("/painel").text
    links = {href for href in re.findall(r'<nav.*?</nav>', painel, re.S)[0].split('"')
             if href.startswith("/")}
    assert {"/painel", "/provas", "/alunos", "/faltas"} <= links

    for link in links:
        resposta = c.get(link, follow_redirects=False)
        assert resposta.status_code in (200, 303), f"{link} devolveu {resposta.status_code}"
    c.__exit__(None, None, None)


def test_pagina_inexistente_e_uma_pagina_e_nao_json():
    c = logar(ADMIN)
    resposta = c.get("/nao-existe", headers={"Accept": "text/html"})
    assert resposta.status_code == 404
    assert "Página não encontrada" in resposta.text
    assert "Voltar ao painel" in resposta.text
    c.__exit__(None, None, None)


def test_api_continua_respondendo_json():
    """Só quem pede HTML recebe página; um cliente de API segue com JSON."""
    c = logar(ADMIN)
    resposta = c.get("/nao-existe", headers={"Accept": "application/json"})
    assert resposta.status_code == 404
    assert resposta.json()["detail"]
    c.__exit__(None, None, None)


@requer_planilha
def test_professor_recebe_pagina_de_403_e_nao_erro_cru():
    c = logar(PROF)
    for rota in ("/alunos", "/faltas"):
        resposta = c.get(rota, headers={"Accept": "text/html"})
        assert resposta.status_code == 403
        assert "Sem acesso a esta área" in resposta.text
    c.__exit__(None, None, None)


# ── faltas ──────────────────────────────────────────────────────────────────────

@requer_planilha
def test_decidir_falta_muda_a_media_da_prova():
    """O que faz a 2ª fase fechar com o relatório.

    Inferência sozinha: 32 presentes e média 3,24. O relatório traz 34 e 3,05 —
    dois alunos fizeram a prova e tiraram zero.
    """
    from app.analytics import metrics as M
    from app.models import Falta, Fase, Materia

    c = logar(ADMIN)
    s = Sessao()
    prova = M.obter_prova(s, 5, Fase.SEGUNDA, Materia.MATEMATICA)
    antes = M.desempenho(s, prova)
    assert len(antes.presentes) == 32

    pendentes = [
        f.id
        for f in s.query(Falta)
        .filter(Falta.prova_id == prova.id, Falta.confirmada.is_(None))
        .all()
    ][:2]
    assert len(pendentes) == 2
    s.close()

    for ident in pendentes:
        assert c.post(f"/faltas/{ident}", data={"decisao": "fez", "volta": "/faltas"}).status_code == 200

    s = Sessao()
    depois = M.desempenho(s, M.obter_prova(s, 5, Fase.SEGUNDA, Materia.MATEMATICA))
    assert len(depois.presentes) == 34
    assert round(depois.media, 2) == 3.05

    for ident in pendentes:                      # devolve o banco ao estado anterior
        s.get(Falta, ident).confirmada = None
    s.commit()
    s.close()
    c.__exit__(None, None, None)


@requer_planilha
def test_tela_de_faltas_explica_a_ambiguidade():
    c = logar(ADMIN)
    texto = c.get("/faltas").text
    assert "não tem coluna de falta" in texto
    assert "tirou zero" in texto      # o caso que a inferência não separa
    c.__exit__(None, None, None)


# ── alunos ──────────────────────────────────────────────────────────────────────

@requer_planilha
def test_tela_de_alunos_marca_quem_entrou_depois():
    c = logar(ADMIN)
    texto = c.get("/alunos").text
    assert "AUGUSTO FABRETE BRAGANCA" in texto
    assert "entrou depois" in texto    # não está na aba do roster
    c.__exit__(None, None, None)


@requer_planilha
def test_tirar_e_devolver_aluno_da_turma():
    from app.models import Aluno

    c = logar(ADMIN)
    s = Sessao()
    aluno = s.query(Aluno).filter(Aluno.ativo.is_(True)).first()
    ident, nome = aluno.id, aluno.nome_canonico
    s.close()

    c.post(f"/alunos/{ident}/remover")
    s = Sessao()
    assert s.get(Aluno, ident).ativo is False
    s.close()

    c.post(f"/alunos/{ident}/devolver")
    s = Sessao()
    assert s.get(Aluno, ident).ativo is True     # lançamentos preservados
    s.close()
    c.__exit__(None, None, None)


# ── enunciados das questões ─────────────────────────────────────────────────────

@requer_planilha
def test_tela_da_prova_mostra_o_enunciado():
    """Ciclo 1 de Química tem o PDF enviado, então os recortes aparecem."""
    c = logar(ADMIN)
    texto = c.get("/provas", params={"ciclo": 1, "fase": "2ª FASE", "materia": "QUÍMICA"}).text
    assert "/questoes/" in texto and "/imagem" in texto
    assert "ver enunciado" in texto
    c.__exit__(None, None, None)


@requer_planilha
def test_imagem_do_enunciado_e_servida():
    import re

    c = logar(ADMIN)
    pagina = c.get("/provas", params={"ciclo": 1, "fase": "2ª FASE", "materia": "QUÍMICA"}).text
    caminho = re.search(r"/questoes/\d+/imagem", pagina).group(0)

    resposta = c.get(caminho)
    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "image/png"
    assert len(resposta.content) > 3000
    c.__exit__(None, None, None)


@requer_planilha
def test_professor_nao_baixa_imagem_de_outra_materia():
    """O endpoint de imagem é uma porta fácil de esquecer no controle de acesso."""
    from app.analytics.metrics import obter_prova
    from app.models import Fase, Materia

    s = Sessao()
    de_matematica = sorted(
        obter_prova(s, 1, Fase.SEGUNDA, Materia.MATEMATICA).questoes, key=lambda q: q.numero
    )[0].id
    de_quimica = sorted(
        obter_prova(s, 1, Fase.SEGUNDA, Materia.QUIMICA).questoes, key=lambda q: q.numero
    )[0].id
    s.close()

    c = logar(PROF)   # professor de Química
    assert c.get(f"/questoes/{de_quimica}/imagem").status_code == 200
    assert c.get(f"/questoes/{de_matematica}/imagem").status_code == 403
    c.__exit__(None, None, None)


def test_imagem_exige_login():
    with TestClient(app, follow_redirects=False) as c:
        assert c.get("/questoes/1/imagem").status_code == 303


@requer_planilha
def test_tela_de_arquivos_e_so_da_coordenacao():
    c = logar(PROF)
    assert c.get("/arquivos", headers={"Accept": "text/html"}).status_code == 403
    c.__exit__(None, None, None)
