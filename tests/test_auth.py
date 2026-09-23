"""Autenticacao, papeis e escopo por materia."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import auth
from app.db import Base
from app.models import Materia, Papel


@pytest.fixture
def s():
    motor = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(motor)
    sessao = sessionmaker(bind=motor, expire_on_commit=False, future=True)()
    yield sessao
    sessao.close()


@pytest.fixture
def coordenacao(s):
    usuario, senha = auth.criar_usuario(
        s, email="Coordenacao@Madan.com.br", nome="Coordenação", papel=Papel.ADMIN
    )
    return usuario, senha


@pytest.fixture
def professora(s):
    usuario, senha = auth.criar_usuario(
        s, email="fisica@madan.com.br", nome="Professora de Física",
        papel=Papel.PROFESSOR, materias=["FÍSICA"],
    )
    return usuario, senha


def test_senha_nao_fica_em_texto_puro(s, coordenacao):
    usuario, senha = coordenacao
    assert senha not in usuario.senha_hash
    assert usuario.senha_hash.startswith("$argon2")


def test_login_confere_a_senha(s, coordenacao):
    usuario, senha = coordenacao
    assert auth.autenticar(s, usuario.email, senha) is not None
    assert auth.autenticar(s, usuario.email, "senha errada") is None
    assert auth.autenticar(s, "nao-existe@madan.com.br", senha) is None


def test_login_ignora_caixa_e_espacos_no_email(s, coordenacao):
    usuario, senha = coordenacao
    assert auth.autenticar(s, "  COORDENACAO@MADAN.COM.BR  ", senha) is not None


def test_conta_inativa_nao_entra(s, coordenacao):
    usuario, senha = coordenacao
    usuario.ativo = False
    s.flush()
    assert auth.autenticar(s, usuario.email, senha) is None


def test_email_duplicado_e_recusado(s, coordenacao):
    with pytest.raises(ValueError, match="Já existe uma conta"):
        auth.criar_usuario(s, email="COORDENACAO@madan.com.br", nome="Outra")


def test_admin_ve_todas_as_materias(s, coordenacao):
    escopo = auth.Escopo(coordenacao[0])
    assert escopo.admin
    assert set(escopo.materias()) == set(Materia)
    for materia in Materia:
        assert escopo.pode_ver(materia)


def test_professor_so_ve_a_propria_materia(s, professora):
    escopo = auth.Escopo(professora[0])
    assert not escopo.admin
    assert escopo.materias() == [Materia.FISICA]
    assert escopo.pode_ver(Materia.FISICA)
    assert not escopo.pode_ver(Materia.QUIMICA)

    with pytest.raises(auth.SemPermissao):
        escopo.exigir(Materia.QUIMICA)
    escopo.exigir(Materia.FISICA)   # nao levanta


def test_professor_com_duas_materias(s):
    usuario, _ = auth.criar_usuario(
        s, email="exatas@madan.com.br", nome="Exatas",
        papel=Papel.PROFESSOR, materias=["MATEMÁTICA", "FÍSICA"],
    )
    escopo = auth.Escopo(usuario)
    assert set(escopo.materias()) == {Materia.MATEMATICA, Materia.FISICA}
    assert not escopo.pode_ver(Materia.QUIMICA)


def test_troca_de_senha(s, professora):
    usuario, senha = professora
    with pytest.raises(ValueError, match="senha atual"):
        auth.trocar_senha(usuario, "errada", "umaSenhaNova123")
    with pytest.raises(ValueError, match="ao menos 8"):
        auth.trocar_senha(usuario, senha, "curta")

    auth.trocar_senha(usuario, senha, "umaSenhaNova123")
    assert auth.autenticar(s, usuario.email, "umaSenhaNova123") is not None
    assert auth.autenticar(s, usuario.email, senha) is None


def test_senha_gerada_tem_tamanho_util():
    senhas = {auth.gerar_senha() for _ in range(50)}
    assert len(senhas) == 50          # sem repetição
    assert all(len(x) == 12 for x in senhas)
