"""Importacao ponta a ponta: da planilha ao banco, conferida contra os relatorios."""

from __future__ import annotations

import statistics

import pytest
from sqlalchemy import select

from app.db import Base
from app.ingest.importers import importar
from app.models import Aluno, Falta, Fase, Materia, Prova, Resposta, ResultadoProva
from tests.conftest import PLANILHA, requer_planilha

# Decisoes da coordenacao (23/09/2026):
#  - Augusto Fabrete e da turma; entrou depois e ficou fora da aba do roster
#  - Arthur Damasceno e Vitor Hoth nao pertencem a turma
ENTROU_DEPOIS = {"AUGUSTO FABRETE BRAGANCA"}
FORA_DA_TURMA = {"ARTHUR DE CARVALHO FARIA DAMASCENO", "VITOR HOTH FRANCESE"}


@pytest.fixture(scope="module")
def banco():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    motor = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(motor)
    return sessionmaker(bind=motor, expire_on_commit=False, future=True)


@pytest.fixture(scope="module")
def importado(banco):
    if not PLANILHA.exists():
        pytest.skip("planilha real ausente")
    s = banco()
    resumo = importar(
        s, PLANILHA, alunos_a_criar=ENTROU_DEPOIS, alunos_a_descartar=FORA_DA_TURMA
    )
    s.commit()
    yield s, resumo
    s.close()


@requer_planilha
def test_resumo_da_importacao(importado):
    _, resumo = importado
    assert resumo.alunos_reconhecidos == 40
    assert resumo.provas == 45          # 5 ciclos x 9 provas
    assert resumo.respostas == 17856
    # Depois das decisoes da coordenacao nao sobra nada para revisar.
    assert resumo.pendencias == []
    assert resumo.sem_dados == []


@requer_planilha
def test_turma_tem_quarenta_alunos_ativos(importado):
    s, _ = importado
    assert s.query(Aluno).filter(Aluno.ativo.is_(True)).count() == 40


@requer_planilha
def test_augusto_e_da_turma_mesmo_fora_do_roster(importado):
    """Entrou depois e ficou fora da aba ALUNOS MADAN 2026, mas e aluno da turma."""
    s, _ = importado
    augusto = s.scalar(select(Aluno).where(Aluno.nome_normalizado == "AUGUSTO FABRETE BRAGANCA"))
    assert augusto is not None
    assert augusto.ativo is True
    assert augusto.no_roster is False   # documenta que a aba esta incompleta


@requer_planilha
def test_descartados_ficam_inativos_e_nao_voltam(importado):
    """Marcados como inativos em vez de apagados, para preservar o historico."""
    s, _ = importado
    for nome in FORA_DA_TURMA:
        aluno = s.scalar(select(Aluno).where(Aluno.nome_normalizado == nome))
        assert aluno is not None and aluno.ativo is False
    # Vitor esta na aba do roster: a reimportacao nao pode ressuscita-lo.
    assert not any(a.ativo for a in s.scalars(
        select(Aluno).where(Aluno.nome_normalizado == "VITOR HOTH FRANCESE")))


@requer_planilha
def test_apelido_nao_duplica_aluno(importado):
    """GONCAVELS e GONCALVES sao a mesma pessoa; nao pode haver dois registros."""
    s, _ = importado
    assert s.query(Aluno).filter(Aluno.nome_normalizado.like("LUCAS EMANUEL%")).count() == 1
    assert s.query(Aluno).filter(Aluno.nome_normalizado.like("MIGUEL GUISAN%")).count() == 1


def _notas_presentes(s, ciclo: int, materia: Materia, fase: Fase = Fase.PRIMEIRA):
    prova = s.scalar(
        select(Prova).where(Prova.ciclo == ciclo, Prova.fase == fase, Prova.materia == materia)
    )
    return sorted(
        (
            r.nota
            for r in s.scalars(
                select(ResultadoProva).where(
                    ResultadoProva.prova_id == prova.id, ResultadoProva.presente.is_(True)
                )
            )
        ),
        reverse=True,
    )


@requer_planilha
def test_ciclo5_matematica_bate_lendo_do_banco(importado):
    """Mesmos numeros do relatorio, agora saindo do banco e nao da planilha."""
    s, _ = importado
    notas = _notas_presentes(s, 5, Materia.MATEMATICA)

    assert len(notas) == 30
    assert round(statistics.mean(notas), 2) == 5.61
    assert sum(1 for n in notas if n > 4.0) == 26
    assert round(statistics.mean(notas[:5]), 2) == 8.67
    assert round(notas[0], 2) == 10.00


@requer_planilha
def test_variacao_ciclo4_para_ciclo5(importado):
    s, _ = importado
    c4 = statistics.mean(_notas_presentes(s, 4, Materia.MATEMATICA))
    c5 = statistics.mean(_notas_presentes(s, 5, Materia.MATEMATICA))
    assert round(c4, 2) == 4.71
    assert round(c5 - c4, 2) == 0.90


@requer_planilha
def test_nivel_e_frente_chegam_nas_questoes(importado):
    s, _ = importado
    prova = s.scalar(
        select(Prova).where(
            Prova.ciclo == 5, Prova.fase == Fase.PRIMEIRA, Prova.materia == Materia.MATEMATICA
        )
    )
    questoes = sorted(prova.questoes, key=lambda q: q.numero)
    assert len(questoes) == 12
    assert all(q.nivel is not None for q in questoes)
    assert all(q.frente and q.frente.startswith("F") for q in questoes)
    # Na 1ª fase a Fisica comeca na questao 13 do caderno.
    fisica = s.scalar(
        select(Prova).where(
            Prova.ciclo == 5, Prova.fase == Fase.PRIMEIRA, Prova.materia == Materia.FISICA
        )
    )
    assert fisica.offset_numeracao == 12
    assert sorted(fisica.questoes, key=lambda q: q.numero)[0].numero_no_caderno == 13


@requer_planilha
def test_faltas_sao_propostas_e_nao_confirmadas(importado):
    """Nenhuma falta vale antes de a coordenacao decidir."""
    s, _ = importado
    assert s.query(Falta).count() > 0
    assert s.query(Falta).filter(Falta.confirmada.is_(None)).count() == s.query(Falta).count()


@requer_planilha
def test_inferencia_de_falta_supera_o_registro_real(importado):
    """A planilha nao distingue quem faltou de quem foi mal.

    O relatorio de faltas contabiliza 44 ausencias de Quimica no ano (3, 5, 7, 16, 13
    por ciclo). A inferencia encontra 48 provas zeradas: 4 alunos fizeram a prova e
    tiraram zero. E por isso que a falta so vira registro depois de confirmada.
    """
    s, _ = importado
    por_ciclo = {}
    for ciclo in range(1, 6):
        prova = s.scalar(
            select(Prova).where(
                Prova.ciclo == ciclo, Prova.fase == Fase.SEGUNDA, Prova.materia == Materia.QUIMICA
            )
        )
        por_ciclo[ciclo] = s.query(Falta).filter(Falta.prova_id == prova.id).count()

    assert por_ciclo == {1: 3, 2: 6, 3: 7, 4: 16, 5: 16}
    assert sum(por_ciclo.values()) == 48          # inferido
    assert sum(por_ciclo.values()) - 44 == 4      # a diferenca que exige revisao humana


@requer_planilha
def test_importar_duas_vezes_nao_duplica(banco):
    """Idempotente, e as decisoes da coordenacao nao precisam ser repetidas.

    Regressao: o reconciliador so conhecia a aba do roster, entao numa reimportacao
    sem repetir `alunos_a_criar` os 36 lancamentos do Augusto eram descartados em
    silencio. Agora ele tambem le os alunos ja cadastrados.
    """
    s = banco()
    importar(s, PLANILHA, alunos_a_criar=ENTROU_DEPOIS, alunos_a_descartar=FORA_DA_TURMA)
    s.commit()
    antes = (s.query(Aluno).count(), s.query(Resposta).count(), s.query(ResultadoProva).count())

    resumo = importar(s, PLANILHA)   # sem repetir nenhuma decisao
    s.commit()
    depois = (s.query(Aluno).count(), s.query(Resposta).count(), s.query(ResultadoProva).count())

    assert antes == depois
    assert resumo.pendencias == []
    assert resumo.alunos_reconhecidos == 40
    s.close()
