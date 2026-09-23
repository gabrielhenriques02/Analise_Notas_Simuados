"""Regras de negocio dos simulados.

Isoladas do calculo para ficarem faceis de conferir contra o que a coordenacao
definiu. Ver CLAUDE.md.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from app.config import config

# Materias que compoem a media geral da 1ª fase.
# Ingles conta para o minimo por materia, mas nao entra na media.
MATERIAS_MEDIA_GERAL = ("MATEMÁTICA", "FÍSICA", "QUÍMICA")
MATERIAS_PRIMEIRA_FASE = ("MATEMÁTICA", "FÍSICA", "QUÍMICA", "INGLÊS")

# Abaixo deste percentual de acerto a questao vira alerta.
# Os relatorios enunciam a regra como "acerto < 50%"; o cabecalho da 1ª fase diz
# "ERRO >= 50%". As duas so divergem numa questao com exatamente 50%, e a legenda
# explicita da 2ª fase manda usar o acerto.
LIMIAR_ACERTO = 50.0

# A lista de enunciados para revisar em sala ignora as dificeis: "as de nivel
# dificil constam apenas na analise acima" (subtitulo da 2ª fase). E por isso que o
# KPI "QUESTOES COM ERRO >= 50%" do Ciclo 5 de Matematica conta 4 e nao 5.
NIVEIS_PARA_REVISAO = ("FÁCIL", "MÉDIO")


class Alerta(str, enum.Enum):
    """CRÍTICA = questão fácil com acerto < 50%; ATENÇÃO = média/difícil idem."""

    CRITICA = "CRÍTICA"
    ATENCAO = "ATENÇÃO"
    NENHUM = ""


def classificar_alerta(nivel: str | None, acerto_pct: float) -> Alerta:
    if acerto_pct >= LIMIAR_ACERTO or nivel is None:
        return Alerta.NENHUM
    return Alerta.CRITICA if nivel == "FÁCIL" else Alerta.ATENCAO


@dataclass(frozen=True)
class Situacao:
    """Resultado de um aluno num ciclo da 1ª fase."""

    aprovado: bool
    geral: float
    materias_cortadas: tuple[str, ...]

    @property
    def rotulo(self) -> str:
        return "APROVADO" if self.aprovado else "CORTADO"

    @property
    def motivo(self) -> str:
        if self.aprovado:
            return ""
        if self.materias_cortadas:
            return "corta em " + ", ".join(_abreviar(m) for m in self.materias_cortadas)
        return f"média geral {formatar(self.geral)} abaixo de {formatar(config.corte_geral)}"


_ABREVIACOES = {"MATEMÁTICA": "MAT", "FÍSICA": "FÍS", "QUÍMICA": "QUÍ", "INGLÊS": "ING"}


def _abreviar(materia: str) -> str:
    return _ABREVIACOES.get(materia, materia[:3])


def media_geral(notas: dict[str, float]) -> float:
    """Media de Mat+Fis+Qui. Ingles fica de fora de proposito."""
    consideradas = [notas[m] for m in MATERIAS_MEDIA_GERAL if m in notas]
    return sum(consideradas) / len(consideradas) if consideradas else 0.0


def avaliar(notas: dict[str, float]) -> Situacao:
    """Aprovado se passar do corte em cada materia E na media de Mat+Fis+Qui.

    Confere com os casos reais dos relatorios:
      Lívia C4   5,83 / 5,00 / 1,67 / 6,67 -> geral 4,17, corta em QUÍ
      Lucas E C1 5,83 / 5,00 / 6,67 / 0,83 -> geral 5,83, corta em ING
    """
    geral = media_geral(notas)
    cortadas = tuple(
        materia
        for materia in MATERIAS_PRIMEIRA_FASE
        if materia in notas and notas[materia] <= config.corte_materia
    )
    aprovado = not cortadas and geral > config.corte_geral
    return Situacao(aprovado=aprovado, geral=geral, materias_cortadas=cortadas)


def indice_dificuldade(niveis: list[str]) -> float | None:
    """1,00 = prova toda fácil; 3,00 = toda difícil."""
    pesos = {"FÁCIL": 1, "MÉDIO": 2, "DIFÍCIL": 3}
    valores = [pesos[n] for n in niveis if n in pesos]
    return sum(valores) / len(valores) if valores else None


def percentil(posicao: int | None, base: int | None = None) -> float | None:
    """Percentil sobre a base de classificados do ciclo (~850 no Poliedro)."""
    if not posicao:
        return None
    return (1 - posicao / (base or config.base_ranking_poliedro)) * 100


# ── formatacao no padrao brasileiro ─────────────────────────────────────────────

def formatar(valor: float | None, casas: int = 2) -> str:
    if valor is None:
        return "—"
    return f"{valor:.{casas}f}".replace(".", ",")


def formatar_sinal(valor: float | None, casas: int = 2) -> str:
    """Variacao entre ciclos: sempre com sinal, como nos relatorios (+0,90 / −0,79)."""
    if valor is None:
        return "—"
    sinal = "+" if valor >= 0 else "−"
    return sinal + formatar(abs(valor), casas)


def formatar_percentual(valor: float | None, casas: int = 0) -> str:
    if valor is None:
        return "—"
    return f"{valor:.{casas}f}".replace(".", ",") + "%"


def formatar_ordinal(posicao: int | None) -> str:
    return f"{posicao}º" if posicao else "—"
