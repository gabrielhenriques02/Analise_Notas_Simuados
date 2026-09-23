"""Visao executiva: a turma inteira, as duas fases, todos os ciclos.

Junta o que a escola mede (correcao dos simulados) com o que o Sistema Poliedro
devolve (classificacao na rede). Sem a classificacao, o relatorio ainda sai — as
colunas de ranking aparecem vazias e o proprio documento diz por que.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import metrics as M
from app.analytics import rules as R
from app.models import Aluno, ClassificacaoPoliedro, Fase, Materia, Questao


@dataclass
class LinhaDoCiclo:
    ciclo: int
    presentes: int = 0
    matriculados: int = 0
    media: float | None = None
    maior_nota: float | None = None
    acima_do_corte_ita: int = 0
    aprovados_1a: int = 0        # criterio do Poliedro
    aprovados_2a: int = 0        # criterio do Poliedro
    aprovados_madan: int = 0     # criterio da coordenacao (rules.avaliar)
    melhor_posicao: int | None = None
    mediana_posicao: int | None = None
    no_top: int = 0
    indice_1a: float | None = None
    indice_2a: float | None = None


@dataclass
class AlunoNoRanking:
    aluno_id: int
    nome: str
    posicoes: dict[int, int | None] = field(default_factory=dict)
    notas: dict[int, float | None] = field(default_factory=dict)
    aprovacoes_1a: int = 0
    aprovacoes_2a: int = 0

    @property
    def realizadas(self) -> list[int]:
        return [p for p in self.posicoes.values() if p]

    @property
    def melhor(self) -> int | None:
        return min(self.realizadas) if self.realizadas else None

    @property
    def media_posicoes(self) -> float | None:
        """Media so sobre os ciclos realizados — quem faltou nao e penalizado."""
        return statistics.mean(self.realizadas) if self.realizadas else None

    @property
    def variacao(self) -> int | None:
        """Do primeiro ao ultimo ciclo com posicao; positivo = subiu no ranking."""
        ordenados = [self.posicoes[c] for c in sorted(self.posicoes) if self.posicoes.get(c)]
        if len(ordenados) < 2:
            return None
        return ordenados[0] - ordenados[-1]


@dataclass
class Unificado:
    ciclos: list[int]
    linhas: list[LinhaDoCiclo] = field(default_factory=list)
    ranking: list[AlunoNoRanking] = field(default_factory=list)
    top: int = 250
    com_classificacao: list[int] = field(default_factory=list)

    @property
    def tem_classificacao(self) -> bool:
        return bool(self.com_classificacao)

    @property
    def melhor_do_periodo(self) -> tuple[str, int, int] | None:
        """(nome, posicao, ciclo) da melhor classificacao ja alcancada."""
        melhor = None
        for aluno in self.ranking:
            for ciclo, posicao in aluno.posicoes.items():
                if posicao and (melhor is None or posicao < melhor[1]):
                    melhor = (aluno.nome, posicao, ciclo)
        return melhor

    @property
    def total_aprovados_1a(self) -> int:
        return sum(l.aprovados_1a for l in self.linhas)

    @property
    def total_aprovados_2a(self) -> int:
        return sum(l.aprovados_2a for l in self.linhas)

    @property
    def total_provas(self) -> int:
        return sum(l.presentes for l in self.linhas)


def _indice(s: Session, ciclo: int, fase: Fase, materias) -> float | None:
    niveis = []
    for materia in materias:
        prova = M.obter_prova(s, ciclo, fase, materia)
        if prova is None:
            continue
        niveis += [q.nivel.value for q in prova.questoes if q.nivel]
    return R.indice_dificuldade(niveis)


def montar(s: Session, ciclos: range | None = None, *, top: int = 250) -> Unificado:
    faixa = list(ciclos or range(1, 6))
    resultado = Unificado(ciclos=faixa, top=top)

    alunos = list(s.scalars(select(Aluno).where(Aluno.ativo.is_(True))))
    classificacoes = {
        (c.aluno_id, c.ciclo, c.fase): c
        for c in s.scalars(select(ClassificacaoPoliedro))
    }
    resultado.com_classificacao = sorted(
        {c.ciclo for c in classificacoes.values() if c.posicao}
    )

    for ciclo in faixa:
        linha = LinhaDoCiclo(ciclo=ciclo, matriculados=len(alunos))

        notas_gerais, aprovados_1a = [], 0
        for aluno in alunos:
            trajeto = M.trajetoria(s, aluno.id, range(ciclo, ciclo + 1))
            if not trajeto or not trajeto[0].presente:
                continue
            situacao = trajeto[0].situacao
            notas_gerais.append(situacao.geral)
            aprovados_1a += 1 if situacao.aprovado else 0

        linha.presentes = len(notas_gerais)
        if notas_gerais:
            linha.media = statistics.mean(notas_gerais)
            linha.maior_nota = max(notas_gerais)
            linha.acima_do_corte_ita = sum(1 for n in notas_gerais if n >= R.config.corte_ita)
        linha.aprovados_madan = aprovados_1a

        # A aprovacao do quadro e a do POLIEDRO, que e o assunto deste relatorio.
        # O criterio da escola aparece a parte, porque os dois nao coincidem.
        linha.aprovados_1a = sum(
            1
            for aluno in alunos
            if (c := classificacoes.get((aluno.id, ciclo, Fase.PRIMEIRA))) and c.aprovado
        )
        linha.aprovados_2a = sum(
            1
            for aluno in alunos
            if (c := classificacoes.get((aluno.id, ciclo, Fase.SEGUNDA))) and c.aprovado
        )

        posicoes = [
            c.posicao
            for aluno in alunos
            if (c := classificacoes.get((aluno.id, ciclo, Fase.SEGUNDA))) and c.posicao
        ]
        if posicoes:
            linha.melhor_posicao = min(posicoes)
            linha.mediana_posicao = int(statistics.median(posicoes))
            linha.no_top = sum(1 for p in posicoes if p <= top)

        linha.indice_1a = _indice(s, ciclo, Fase.PRIMEIRA, R.MATERIAS_MEDIA_GERAL)
        linha.indice_2a = _indice(s, ciclo, Fase.SEGUNDA, R.MATERIAS_MEDIA_GERAL)
        resultado.linhas.append(linha)

    for aluno in alunos:
        registro = AlunoNoRanking(aluno.id, aluno.nome_canonico)
        for ciclo in faixa:
            final = classificacoes.get((aluno.id, ciclo, Fase.SEGUNDA))
            primeira = classificacoes.get((aluno.id, ciclo, Fase.PRIMEIRA))
            registro.posicoes[ciclo] = final.posicao if final else None
            registro.notas[ciclo] = (
                primeira.nota if primeira and primeira.nota is not None
                else (final.nota if final else None)
            )
            trajeto = M.trajetoria(s, aluno.id, range(ciclo, ciclo + 1))
            if primeira and primeira.aprovado:
                registro.aprovacoes_1a += 1
            elif primeira is None and trajeto and trajeto[0].presente and trajeto[0].situacao.aprovado:
                registro.aprovacoes_1a += 1     # sem dado do Poliedro, vale o da escola
            if final and final.aprovado:
                registro.aprovacoes_2a += 1
        resultado.ranking.append(registro)

    resultado.ranking.sort(
        key=lambda a: (a.media_posicoes if a.media_posicoes is not None else 1e9, a.nome)
    )
    return resultado


def faixa_da_posicao(posicao: int | None, top: int = 250) -> str:
    if not posicao:
        return "sem"
    if posicao <= top:
        return "topo"
    if posicao <= top * 1.8:
        return "meio"
    return "fundo"
