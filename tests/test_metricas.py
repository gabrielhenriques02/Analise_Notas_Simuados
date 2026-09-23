"""Metricas conferidas contra os relatorios de referencia."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.analytics import metrics as M
from app.analytics import rules as R
from app.models import Falta, Fase, Materia
from tests.conftest import requer_planilha


# ── regras puras (nao dependem da planilha) ─────────────────────────────────────

def test_criterio_de_aprovacao_com_os_casos_reais():
    """> 4,0 em cada matéria E > 5,0 na média de Mat+Fís+Quí."""
    livia = R.avaliar({"MATEMÁTICA": 5.83, "FÍSICA": 5.00, "QUÍMICA": 1.67, "INGLÊS": 6.67})
    assert not livia.aprovado
    assert livia.materias_cortadas == ("QUÍMICA",)
    assert round(livia.geral, 2) == 4.17

    # Geral acima de 5,0, mas o inglês corta — ele conta para o mínimo por matéria.
    lucas = R.avaliar({"MATEMÁTICA": 5.83, "FÍSICA": 5.00, "QUÍMICA": 6.67, "INGLÊS": 0.83})
    assert not lucas.aprovado
    assert lucas.materias_cortadas == ("INGLÊS",)
    assert round(lucas.geral, 2) == 5.83

    murilo = R.avaliar({"MATEMÁTICA": 10.0, "FÍSICA": 7.50, "QUÍMICA": 8.33, "INGLÊS": 9.17})
    assert murilo.aprovado
    assert round(murilo.geral, 2) == 8.61


def test_ingles_fica_fora_da_media_geral():
    notas = {"MATEMÁTICA": 6.0, "FÍSICA": 6.0, "QUÍMICA": 6.0, "INGLÊS": 0.0}
    assert R.media_geral(notas) == 6.0


def test_indice_de_dificuldade():
    """Ciclo 1 da 1ª fase: 11 fáceis, 12 médias, 13 difíceis em 36 questões."""
    niveis = ["FÁCIL"] * 11 + ["MÉDIO"] * 12 + ["DIFÍCIL"] * 13
    assert round(R.indice_dificuldade(niveis), 2) == 2.06
    assert R.indice_dificuldade(["FÁCIL"] * 10) == 1.0
    assert R.indice_dificuldade(["DIFÍCIL"] * 10) == 3.0


def test_alerta_segue_o_nivel():
    assert R.classificar_alerta("FÁCIL", 40.0) is R.Alerta.CRITICA
    assert R.classificar_alerta("MÉDIO", 40.0) is R.Alerta.ATENCAO
    assert R.classificar_alerta("DIFÍCIL", 40.0) is R.Alerta.ATENCAO
    assert R.classificar_alerta("FÁCIL", 60.0) is R.Alerta.NENHUM


@pytest.mark.parametrize(
    "valor, esperado", [(5.61, "5,61"), (-0.79, "-0,79"), (None, "—"), (10.0, "10,00")]
)
def test_formatacao_brasileira(valor, esperado):
    assert R.formatar(valor) == esperado


def test_formatacao_de_variacao():
    assert R.formatar_sinal(0.90) == "+0,90"
    assert R.formatar_sinal(-0.79) == "−0,79"   # sinal de menos, como no relatório


# ── conferencia contra os relatorios ────────────────────────────────────────────

@pytest.fixture(scope="module")
def sessao_banco():
    from app.db import Sessao

    s = Sessao()
    yield s
    s.rollback()
    s.close()


@requer_planilha
def test_ciclo5_1a_fase_matematica(sessao_banco):
    """Relatorio - Ciclo 5 - 1a Fase - Matematica.pdf, KPIs da página 1."""
    s = sessao_banco
    d = M.desempenho(s, M.obter_prova(s, 5, Fase.PRIMEIRA, Materia.MATEMATICA))

    assert len(d.presentes) == 30
    assert len(d.ausentes) == 9
    assert round(d.media, 2) == 5.61
    assert d.acima_do_corte == 26
    assert round(d.percentual_acima_do_corte) == 87
    assert round(d.media_top, 2) == 8.67
    assert round(d.maior_nota, 2) == 10.00


@requer_planilha
def test_variacao_e_serie_dos_ciclos(sessao_banco):
    s = sessao_banco
    variacao, anterior = M.variacao_entre_ciclos(s, 5, Fase.PRIMEIRA, Materia.MATEMATICA)
    assert round(variacao, 2) == 0.90
    assert round(anterior, 2) == 4.71

    serie = M.serie_de_medias(s, Fase.PRIMEIRA, Materia.MATEMATICA)
    assert [round(x, 2) for x in serie] == [4.98, 4.15, 4.62, 4.71, 5.61]


@requer_planilha
def test_questoes_para_revisar_ignoram_as_dificeis(sessao_banco):
    """O KPI conta 4: "1 de nível fácil · 3 de nível médio".

    Uma quinta questão passa de 50% de erro, mas é difícil — e o relatório diz
    que "as de nível difícil constam apenas na análise acima".
    """
    s = sessao_banco
    d = M.desempenho(s, M.obter_prova(s, 5, Fase.PRIMEIRA, Materia.MATEMATICA))
    revisar = d.questoes_para_revisar

    assert len(revisar) == 4
    assert sum(1 for q in revisar if q.nivel == "FÁCIL") == 1
    assert sum(1 for q in revisar if q.nivel == "MÉDIO") == 3
    assert all(q.nivel != "DIFÍCIL" for q in revisar)
    # ordenadas da pior para a melhor
    assert [round(q.erro_pct) for q in revisar] == sorted(
        (round(q.erro_pct) for q in revisar), reverse=True
    )
    # a difícil existe e continua aparecendo na análise por questão
    assert any(q.nivel == "DIFÍCIL" and q.erro_pct > 50 for q in d.questoes)


@requer_planilha
def test_aproveitamento_por_nivel_e_frente(sessao_banco):
    """FÁCIL 67% (7 q.), MÉDIA 46% (4 q.), DIFÍCIL 23% (1 q.);
    frentes F4 23%, F3 44%, F5 48%, F1 69%, F2 71%."""
    s = sessao_banco
    d = M.desempenho(s, M.obter_prova(s, 5, Fase.PRIMEIRA, Materia.MATEMATICA))

    niveis = {a.rotulo: (a.questoes, round(a.aproveitamento)) for a in d.por_nivel()}
    assert niveis == {"FÁCIL": (7, 67), "MÉDIO": (4, 46), "DIFÍCIL": (1, 23)}

    frentes = [(a.rotulo, a.questoes, round(a.aproveitamento)) for a in d.por_frente()]
    assert frentes == [("F4", 1, 23), ("F3", 3, 44), ("F5", 2, 48), ("F1", 3, 69), ("F2", 3, 71)]


@requer_planilha
def test_2a_fase_depende_da_falta_confirmada(sessao_banco):
    """A inferência por prova zerada conta 2 ausentes a mais do que o relatório.

    Relatorio - Ciclo 5 - 2a Fase - Matematica.pdf: 34 avaliados, média 3,05,
    mediana 2,60, Q1 com média 4,79/10. Só se chega lá quando a coordenação
    confirma que dois dos zerados fizeram a prova.
    """
    s = sessao_banco
    prova = M.obter_prova(s, 5, Fase.SEGUNDA, Materia.MATEMATICA)

    inferido = M.desempenho(s, prova)
    assert len(inferido.presentes) == 32          # inferência sozinha
    assert round(inferido.media, 2) == 3.24

    faltas = list(s.scalars(select(Falta).where(Falta.prova_id == prova.id)))
    assert len(faltas) == 7                       # relatório registra 5
    for falta in faltas[:2]:
        falta.confirmada = False
    s.flush()

    corrigido = M.desempenho(s, prova)
    assert len(corrigido.presentes) == 34
    assert round(corrigido.media, 2) == 3.05
    assert round(corrigido.mediana, 2) == 2.60
    assert round(corrigido.media_top, 2) == 6.36
    assert round(corrigido.maior_nota, 2) == 7.00

    q1 = corrigido.questoes[0]
    assert round(q1.media, 2) == 4.79
    assert round(q1.acerto_pct, 1) == 47.9
    assert round(q1.erro_pct) == 52
    assert q1.alerta is R.Alerta.ATENCAO

    s.rollback()


@requer_planilha
def test_regularidade_e_desvio_populacional(sessao_banco):
    """Murilo: 8,61 / 7,22 / 7,22 / 6,94 / 8,61 -> 0,73 (populacional, não amostral)."""
    from app.models import Aluno

    s = sessao_banco
    murilo = s.scalar(select(Aluno).where(Aluno.nome_normalizado == "MURILO COSER ROCHA"))
    trajeto = M.trajetoria(s, murilo.id)

    assert [round(c.geral, 2) for c in trajeto] == [8.61, 7.22, 7.22, 6.94, 8.61]
    assert round(M.regularidade(trajeto), 2) == 0.73
    assert all(c.situacao.aprovado for c in trajeto)   # 5/5 aprovações
