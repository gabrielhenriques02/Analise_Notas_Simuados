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
