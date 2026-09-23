"""Dossie individual dos alunos com mais chance de aprovacao.

O criterio de aprovacao vem de rules.avaliar: acima do corte em cada materia E na
media de Mat+Fis+Qui. Aqui a pergunta e outra — nao "quem passou", mas "o que
especificamente esta travando quem chegou perto".
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import metrics as M
from app.analytics import rules as R
from app.models import Aluno, Fase, Materia, Questao, Resposta, ResultadoProva

MINIMO_QUESTOES_FRENTE = 4     # frente com menos que isso nao vira diagnostico
DESTAQUES = 8


@dataclass
class Frente:
    materia: str
    frente: str
    acertos: int
    total: int

    @property
    def aproveitamento(self) -> float:
        return self.acertos / self.total * 100 if self.total else 0.0

    @property
    def rotulo(self) -> str:
        return f"{R._abreviar(self.materia)} · {self.frente}"


@dataclass
class Dossie:
    aluno_id: int
    nome: str
    trajetoria: list[M.CicloDoAluno] = field(default_factory=list)
    niveis: dict[tuple[str, str], tuple[float, float]] = field(default_factory=dict)
    frentes: list[Frente] = field(default_factory=list)
    faceis_perdidas: int = 0
    provas_feitas: int = 0

    @property
    def aprovacoes(self) -> int:
        return sum(1 for c in self.trajetoria if c.presente and c.situacao.aprovado)

    @property
    def realizados(self) -> int:
        return sum(1 for c in self.trajetoria if c.presente)

    @property
    def media_geral(self) -> float | None:
        gerais = [c.geral for c in self.trajetoria if c.presente]
        return statistics.mean(gerais) if gerais else None

    @property
    def melhor(self) -> float | None:
        gerais = [c.geral for c in self.trajetoria if c.presente]
        return max(gerais) if gerais else None

    @property
    def pior(self) -> float | None:
        gerais = [c.geral for c in self.trajetoria if c.presente]
        return min(gerais) if gerais else None

    @property
    def regularidade(self) -> float | None:
        return M.regularidade(self.trajetoria)

    @property
    def variacao_recente(self) -> float | None:
        feitos = [c for c in self.trajetoria if c.presente]
        if len(feitos) < 2:
            return None
        return feitos[-1].geral - feitos[-2].geral

    @property
    def faceis_por_prova(self) -> float | None:
        return self.faceis_perdidas / self.provas_feitas if self.provas_feitas else None

    @property
    def cortes(self) -> dict[str, int]:
        """Quantas vezes cada materia foi o motivo do corte."""
        contagem: dict[str, int] = {}
        for ciclo in self.trajetoria:
            if not ciclo.presente:
                continue
            for materia in ciclo.situacao.materias_cortadas:
                contagem[materia] = contagem.get(materia, 0) + 1
        return contagem

    @property
    def travamento(self) -> Frente | None:
        return self.frentes[0] if self.frentes else None

    @property
    def segundo_ponto(self) -> Frente | None:
        return self.frentes[1] if len(self.frentes) > 1 else None

    @property
    def veredito(self) -> str:
        """Uma frase que resume o caso — o resto e leitura da coordenacao."""
        if not self.realizados:
            return "Sem provas realizadas no período."
        if self.aprovacoes == self.realizados:
            return (
                f"Aprovado nos {self.realizados} ciclos que realizou, "
                "sem nenhum corte por disciplina."
            )
        if self.aprovacoes == 0:
            cortes = self.cortes
            if cortes:
                pior = max(cortes, key=lambda m: cortes[m])
                return (
                    f"Nenhuma aprovação em {self.realizados} ciclos — sempre eliminado "
                    f"por uma disciplina, mais vezes por {pior.lower()}."
                )
            return f"Nenhuma aprovação em {self.realizados} ciclos."
        return (
            f"{self.aprovacoes} aprovações em {self.realizados} ciclos; "
            f"o que corta é {', '.join(m.lower() for m in self.cortes)}."
        )


def _frentes_do_aluno(s: Session, aluno_id: int, ciclos: range) -> list[Frente]:
    baldes: dict[tuple[str, str], list[int]] = {}
    for ciclo in ciclos:
        for materia in R.MATERIAS_PRIMEIRA_FASE:
            prova = M.obter_prova(s, ciclo, Fase.PRIMEIRA, materia)
            if prova is None:
                continue
            resultado = s.scalar(
                select(ResultadoProva).where(
                    ResultadoProva.aluno_id == aluno_id, ResultadoProva.prova_id == prova.id
                )
            )
            if resultado is None or not resultado.presente:
                continue
            questoes = {q.id: q for q in s.scalars(select(Questao).where(Questao.prova_id == prova.id))}
            for resposta in s.scalars(
                select(Resposta).where(
                    Resposta.aluno_id == aluno_id, Resposta.questao_id.in_(list(questoes))
                )
            ):
                questao = questoes[resposta.questao_id]
                if not questao.frente:
                    continue
                chave = (materia, questao.frente)
                baldes.setdefault(chave, []).append(
                    1 if resposta.nota >= prova.nota_maxima_questao else 0
                )

    frentes = [
        Frente(materia, frente, sum(acertos), len(acertos))
        for (materia, frente), acertos in baldes.items()
        if len(acertos) >= MINIMO_QUESTOES_FRENTE
    ]
    return sorted(frentes, key=lambda f: (f.aproveitamento, -f.total))


def _faceis_perdidas(s: Session, aluno_id: int, ciclos: range) -> tuple[int, int]:
    """Questoes faceis erradas em Mat+Fis+Qui e quantas provas o aluno fez."""
    perdidas = 0
    provas = 0
    for ciclo in ciclos:
        fez = False
        for materia in R.MATERIAS_MEDIA_GERAL:
            prova = M.obter_prova(s, ciclo, Fase.PRIMEIRA, materia)
            if prova is None:
                continue
            resultado = s.scalar(
                select(ResultadoProva).where(
                    ResultadoProva.aluno_id == aluno_id, ResultadoProva.prova_id == prova.id
                )
            )
            if resultado is None or not resultado.presente:
                continue
            fez = True
            faceis = {
                q.id for q in s.scalars(select(Questao).where(Questao.prova_id == prova.id))
                if q.nivel and q.nivel.value == "FÁCIL"
            }
            if not faceis:
                continue
            for resposta in s.scalars(
                select(Resposta).where(
                    Resposta.aluno_id == aluno_id, Resposta.questao_id.in_(faceis)
                )
            ):
                if resposta.nota < prova.nota_maxima_questao:
                    perdidas += 1
        provas += 1 if fez else 0
    return perdidas, provas


def dossie(s: Session, aluno: Aluno, ciclos: range | None = None) -> Dossie:
    ciclos = ciclos or range(1, 6)
    perdidas, provas = _faceis_perdidas(s, aluno.id, ciclos)
    return Dossie(
        aluno_id=aluno.id,
        nome=aluno.nome_canonico,
        trajetoria=M.trajetoria(s, aluno.id, ciclos),
        niveis=M.aproveitamento_por_nivel(s, aluno.id, ciclos),
        frentes=_frentes_do_aluno(s, aluno.id, ciclos),
        faceis_perdidas=perdidas,
        provas_feitas=provas,
    )


def destaques(s: Session, quantos: int = DESTAQUES, ciclos: range | None = None) -> list[Dossie]:
    """Os alunos com mais chance de aprovacao, por media geral da 1ª fase.

    Empate desempata por numero de aprovacoes — quem ja passou alguma vez esta mais
    perto do que quem tem a mesma media sem nunca ter passado.
    """
    ciclos = ciclos or range(1, 6)
    candidatos = []
    for aluno in s.scalars(select(Aluno).where(Aluno.ativo.is_(True))):
        registro = dossie(s, aluno, ciclos)
        if registro.realizados:
            candidatos.append(registro)
    candidatos.sort(key=lambda d: (-(d.media_geral or 0), -d.aprovacoes, d.nome))
    return candidatos[:quantos]


def cortes_do_grupo(grupo: list[Dossie]) -> dict[str, int]:
    total: dict[str, int] = {}
    for registro in grupo:
        for materia, quantidade in registro.cortes.items():
            total[materia] = total.get(materia, 0) + quantidade
    return dict(sorted(total.items(), key=lambda x: -x[1]))
