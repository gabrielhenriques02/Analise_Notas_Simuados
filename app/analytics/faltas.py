"""Analise de faltas.

A planilha nao tem coluna de falta: o sistema infere a partir da prova zerada e a
coordenacao confirma. Aqui, uma ausencia conta enquanto nao for explicitamente
descartada — mesma regra que as metricas usam para presenca, para os dois numeros
nunca discordarem.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Aluno, Falta, Fase, Materia, Prova

CICLOS_RECENTES = 2      # "os dois ultimos ciclos" das listas de prioridade
REINCIDENCIA = 3         # a partir daqui, reincidencia cronica


@dataclass
class AlunoFaltoso:
    aluno_id: int
    nome: str
    faltas: dict[int, bool] = field(default_factory=dict)   # ciclo -> faltou

    @property
    def total(self) -> int:
        return sum(1 for faltou in self.faltas.values() if faltou)

    @property
    def ciclos(self) -> int:
        return len(self.faltas)

    @property
    def percentual(self) -> float:
        return self.total / self.ciclos * 100 if self.ciclos else 0.0

    def faltou_em(self, ciclos: list[int]) -> int:
        return sum(1 for ciclo in ciclos if self.faltas.get(ciclo))

    @property
    def cronico(self) -> bool:
        return self.total >= REINCIDENCIA

    def primeira_falta(self) -> int | None:
        for ciclo in sorted(self.faltas):
            if self.faltas[ciclo]:
                return ciclo
        return None


@dataclass
class Panorama:
    materia: Materia
    fase: Fase
    ciclos: list[int]
    turma: int
    por_ciclo: dict[int, int] = field(default_factory=dict)
    alunos: list[AlunoFaltoso] = field(default_factory=list)
    pendentes: int = 0

    @property
    def total(self) -> int:
        return sum(self.por_ciclo.values())

    def percentual(self, ciclo: int) -> float:
        return self.por_ciclo.get(ciclo, 0) / self.turma * 100 if self.turma else 0.0

    @property
    def recentes(self) -> list[int]:
        return self.ciclos[-CICLOS_RECENTES:]

    @property
    def anteriores(self) -> list[int]:
        return self.ciclos[:-CICLOS_RECENTES]

    @property
    def salto(self) -> float | None:
        """Quanto a media de faltas subiu dos primeiros ciclos para os dois ultimos."""
        antes = [self.por_ciclo.get(c, 0) for c in self.anteriores]
        depois = [self.por_ciclo.get(c, 0) for c in self.recentes]
        if not antes or not depois or not statistics.mean(antes):
            return None
        return (statistics.mean(depois) / statistics.mean(antes) - 1) * 100

    @property
    def media_anterior(self) -> float:
        return statistics.mean([self.por_ciclo.get(c, 0) for c in self.anteriores] or [0])

    @property
    def media_recente(self) -> float:
        return statistics.mean([self.por_ciclo.get(c, 0) for c in self.recentes] or [0])

    # ── grupos de acompanhamento ────────────────────────────────────────────────

    @property
    def prioridade_1(self) -> list[AlunoFaltoso]:
        """Perderam os dois ultimos ciclos."""
        return sorted(
            (a for a in self.alunos if a.faltou_em(self.recentes) == len(self.recentes)),
            key=lambda a: (-a.total, a.nome),
        )

    @property
    def prioridade_2(self) -> list[AlunoFaltoso]:
        """Perderam um dos dois ultimos."""
        return sorted(
            (a for a in self.alunos if a.faltou_em(self.recentes) == 1),
            key=lambda a: (-a.total, a.nome),
        )

    @property
    def cronicos(self) -> list[AlunoFaltoso]:
        return sorted((a for a in self.alunos if a.cronico), key=lambda a: (-a.total, a.nome))

    @property
    def comecaram_agora(self) -> list[AlunoFaltoso]:
        """Presenca integral ate os ciclos anteriores; a primeira falta e recente."""
        return sorted(
            (
                a for a in self.alunos
                if a.total and (a.primeira_falta() in self.recentes)
            ),
            key=lambda a: a.nome,
        )

    @property
    def presenca_integral(self) -> list[AlunoFaltoso]:
        return sorted((a for a in self.alunos if not a.total), key=lambda a: a.nome)

    @property
    def envolvidos(self) -> list[AlunoFaltoso]:
        """Quem faltou em pelo menos um dos dois ultimos ciclos."""
        return sorted(
            (a for a in self.alunos if a.faltou_em(self.recentes)), key=lambda a: a.nome
        )

    @property
    def distribuicao(self) -> list[tuple[str, int]]:
        faixas = [("Nenhuma falta", 0), ("1 falta", 1), ("2 faltas", 2), ("3 ou mais", 3)]
        saida = []
        for rotulo, quantidade in faixas:
            if quantidade < 3:
                total = sum(1 for a in self.alunos if a.total == quantidade)
            else:
                total = sum(1 for a in self.alunos if a.total >= 3)
            saida.append((rotulo, total))
        return saida


def panorama(s: Session, materia: Materia, fase: Fase) -> Panorama:
    provas = list(
        s.scalars(
            select(Prova)
            .where(Prova.fase == fase, Prova.materia == materia)
            .order_by(Prova.ciclo)
        )
    )
    if not provas:
        return Panorama(materia, fase, [], 0)

    ciclos = [p.ciclo for p in provas]
    por_prova = {p.id: p.ciclo for p in provas}

    alunos = {
        a.id: AlunoFaltoso(a.id, a.nome_canonico, {c: False for c in ciclos})
        for a in s.scalars(select(Aluno).where(Aluno.ativo.is_(True)))
    }

    pendentes = 0
    por_ciclo = dict.fromkeys(ciclos, 0)
    for falta in s.scalars(select(Falta).where(Falta.prova_id.in_(por_prova))):
        if falta.confirmada is False:          # a coordenacao disse que fez a prova
            continue
        if falta.confirmada is None:
            pendentes += 1
        registro = alunos.get(falta.aluno_id)
        if registro is None:
            continue
        ciclo = por_prova[falta.prova_id]
        registro.faltas[ciclo] = True
        por_ciclo[ciclo] += 1

    resultado = Panorama(materia, fase, ciclos, len(alunos), por_ciclo, list(alunos.values()))
    resultado.pendentes = pendentes
    return resultado
