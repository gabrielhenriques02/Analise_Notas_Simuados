"""Calculo das metricas dos simulados, lendo do banco.

Regra transversal: ausentes ficam fora de toda estatistica e sao listados a parte.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import rules
from app.models import Aluno, Falta, Fase, Materia, Prova, Questao, Resposta, ResultadoProva

TOP = 5  # "MÉDIA DOS 5 MELHORES"


@dataclass
class DesempenhoAluno:
    aluno_id: int
    nome: str
    nota: float
    notas_por_questao: dict[int, float] = field(default_factory=dict)

    def acertou(self, numero: int, maxima: float) -> bool:
        return self.notas_por_questao.get(numero, 0.0) >= maxima


@dataclass
class EstatisticaQuestao:
    numero: int
    numero_no_caderno: int
    nivel: str | None
    frente: str | None
    presentes: int
    acertos: int          # nota maxima
    media: float          # media da nota na questao
    acerto_pct: float
    # Distribuicao das correcoes na 2ª fase: nota maxima / parcial >=50% / parcial <50% / zerada
    maxima: int = 0
    parcial_alta: int = 0
    parcial_baixa: int = 0
    zerada: int = 0

    @property
    def erro_pct(self) -> float:
        return 100.0 - self.acerto_pct

    @property
    def alerta(self) -> rules.Alerta:
        return rules.classificar_alerta(self.nivel, self.acerto_pct)

    @property
    def para_revisar(self) -> bool:
        """Entra na lista de enunciados a revisar em sala (dificeis ficam de fora)."""
        return self.acerto_pct < rules.LIMIAR_ACERTO and self.nivel in rules.NIVEIS_PARA_REVISAO


@dataclass
class Agrupamento:
    """Aproveitamento por frente ou por nivel."""

    rotulo: str
    questoes: int
    aproveitamento: float


@dataclass
class DesempenhoProva:
    prova: Prova
    presentes: list[DesempenhoAluno]
    ausentes: list[str]
    questoes: list[EstatisticaQuestao]

    @property
    def total_matriculados(self) -> int:
        return len(self.presentes) + len(self.ausentes)

    @property
    def notas(self) -> list[float]:
        return sorted((a.nota for a in self.presentes), reverse=True)

    @property
    def media(self) -> float | None:
        return statistics.mean(self.notas) if self.notas else None

    @property
    def mediana(self) -> float | None:
        return statistics.median(self.notas) if self.notas else None

    @property
    def maior_nota(self) -> float | None:
        return self.notas[0] if self.notas else None

    @property
    def media_top(self) -> float | None:
        return statistics.mean(self.notas[:TOP]) if self.notas else None

    @property
    def acima_do_corte(self) -> int:
        from app.config import config

        return sum(1 for n in self.notas if n > config.corte_materia)

    @property
    def percentual_acima_do_corte(self) -> float | None:
        if not self.notas:
            return None
        return self.acima_do_corte / len(self.notas) * 100

    @property
    def questoes_para_revisar(self) -> list[EstatisticaQuestao]:
        """Faceis e medias com acerto < 50%, da pior para a melhor.

        E o que alimenta o KPI "QUESTÕES COM ERRO >= 50%" e a secao de enunciados.
        """
        return sorted(
            (q for q in self.questoes if q.para_revisar), key=lambda q: q.erro_pct, reverse=True
        )

    def por_frente(self) -> list[Agrupamento]:
        """Ordenado do pior para o melhor, como nos relatorios."""
        return sorted(self._agrupar(lambda q: q.frente), key=lambda a: a.aproveitamento)

    def por_nivel(self) -> list[Agrupamento]:
        """Ordem fixa fácil -> médio -> difícil."""
        ordem = {"FÁCIL": 0, "MÉDIO": 1, "DIFÍCIL": 2}
        return sorted(
            self._agrupar(lambda q: q.nivel), key=lambda a: ordem.get(a.rotulo, 9)
        )

    def _agrupar(self, chave) -> list[Agrupamento]:
        baldes: dict[str, list[EstatisticaQuestao]] = {}
        for questao in self.questoes:
            valor = chave(questao)
            if valor:
                baldes.setdefault(valor, []).append(questao)
        saida = []
        for rotulo, questoes in baldes.items():
            presentes = sum(q.presentes for q in questoes)
            if not presentes:
                continue
            obtido = sum(q.media * q.presentes for q in questoes)
            possivel = self.prova.nota_maxima_questao * presentes
            saida.append(
                Agrupamento(rotulo, len(questoes), obtido / possivel * 100 if possivel else 0.0)
            )
        return saida


def obter_prova(s: Session, ciclo: int, fase: Fase | str, materia: Materia | str) -> Prova | None:
    return s.scalar(
        select(Prova).where(
            Prova.ciclo == ciclo,
            Prova.fase == (fase if isinstance(fase, Fase) else Fase(fase)),
            Prova.materia == (materia if isinstance(materia, Materia) else Materia(materia)),
        )
    )


def desempenho(s: Session, prova: Prova) -> DesempenhoProva:
    """Monta o quadro completo de uma prova: alunos, ausentes e estatistica por questao."""
    questoes = sorted(
        s.scalars(select(Questao).where(Questao.prova_id == prova.id)), key=lambda q: q.numero
    )
    por_id = {q.id: q for q in questoes}

    resultados = list(
        s.scalars(
            select(ResultadoProva)
            .join(Aluno, Aluno.id == ResultadoProva.aluno_id)
            .where(ResultadoProva.prova_id == prova.id, Aluno.ativo.is_(True))
        )
    )
    nomes = {
        a.id: a.nome_canonico
        for a in s.scalars(select(Aluno).where(Aluno.id.in_([r.aluno_id for r in resultados])))
    }

    # A inferencia por prova zerada erra quando o aluno fez a prova e tirou zero.
    # Quando a coordenacao marca a falta como nao confirmada, ele volta a contar.
    nao_faltou = {
        f.aluno_id
        for f in s.scalars(
            select(Falta).where(Falta.prova_id == prova.id, Falta.confirmada.is_(False))
        )
    }
    esteve = {r.aluno_id: (r.presente or r.aluno_id in nao_faltou) for r in resultados}

    presentes_ids = [r.aluno_id for r in resultados if esteve[r.aluno_id]]
    respostas: dict[int, dict[int, float]] = {}
    if presentes_ids:
        for resposta in s.scalars(
            select(Resposta).where(
                Resposta.aluno_id.in_(presentes_ids),
                Resposta.questao_id.in_(list(por_id)),
            )
        ):
            numero = por_id[resposta.questao_id].numero
            respostas.setdefault(resposta.aluno_id, {})[numero] = resposta.nota

    presentes = sorted(
        (
            DesempenhoAluno(
                aluno_id=r.aluno_id,
                nome=nomes.get(r.aluno_id, "?"),
                nota=r.nota or 0.0,
                notas_por_questao=respostas.get(r.aluno_id, {}),
            )
            for r in resultados
            if esteve[r.aluno_id]
        ),
        key=lambda a: (-a.nota, a.nome),
    )
    ausentes = sorted(nomes.get(r.aluno_id, "?") for r in resultados if not esteve[r.aluno_id])

    return DesempenhoProva(
        prova=prova,
        presentes=presentes,
        ausentes=ausentes,
        questoes=[_estatistica(q, prova, presentes) for q in questoes],
    )


def _estatistica(questao: Questao, prova: Prova, presentes: list[DesempenhoAluno]) -> EstatisticaQuestao:
    maxima = prova.nota_maxima_questao
    notas = [a.notas_por_questao.get(questao.numero, 0.0) for a in presentes]
    total = len(notas)
    media = statistics.mean(notas) if notas else 0.0

    return EstatisticaQuestao(
        numero=questao.numero,
        numero_no_caderno=questao.numero + prova.offset_numeracao,
        nivel=questao.nivel.value if questao.nivel else None,
        frente=questao.frente,
        presentes=total,
        acertos=sum(1 for n in notas if n >= maxima),
        media=media,
        acerto_pct=(media / maxima * 100) if maxima else 0.0,
        maxima=sum(1 for n in notas if n >= maxima),
        parcial_alta=sum(1 for n in notas if maxima / 2 <= n < maxima),
        parcial_baixa=sum(1 for n in notas if 0 < n < maxima / 2),
        zerada=sum(1 for n in notas if n <= 0),
    )


def variacao_entre_ciclos(s: Session, ciclo: int, fase: Fase, materia: Materia) -> tuple[float | None, float | None]:
    """Devolve (variacao, media do ciclo anterior)."""
    atual = obter_prova(s, ciclo, fase, materia)
    anterior = obter_prova(s, ciclo - 1, fase, materia)
    if atual is None or anterior is None:
        return None, None
    media_atual = desempenho(s, atual).media
    media_anterior = desempenho(s, anterior).media
    if media_atual is None or media_anterior is None:
        return None, media_anterior
    return media_atual - media_anterior, media_anterior


def serie_de_medias(s: Session, fase: Fase, materia: Materia, ciclos: range | None = None) -> list[float | None]:
    """"Série dos ciclos: 4,98 · 4,15 · 4,62 · 4,71 · 5,61" dos relatorios."""
    saida = []
    for ciclo in ciclos or range(1, 6):
        prova = obter_prova(s, ciclo, fase, materia)
        saida.append(desempenho(s, prova).media if prova else None)
    return saida


# ── visao do aluno ──────────────────────────────────────────────────────────────

@dataclass
class CicloDoAluno:
    ciclo: int
    notas: dict[str, float]
    presente: bool

    @property
    def situacao(self) -> rules.Situacao:
        return rules.avaliar(self.notas)

    @property
    def geral(self) -> float:
        return rules.media_geral(self.notas)


def trajetoria(s: Session, aluno_id: int, ciclos: range | None = None) -> list[CicloDoAluno]:
    """Notas da 1ª fase por ciclo — a tabela TRAJETÓRIA NOS CINCO CICLOS."""
    saida = []
    for ciclo in ciclos or range(1, 6):
        notas: dict[str, float] = {}
        presente = False
        for materia in rules.MATERIAS_PRIMEIRA_FASE:
            prova = obter_prova(s, ciclo, Fase.PRIMEIRA, materia)
            if prova is None:
                continue
            resultado = s.scalar(
                select(ResultadoProva).where(
                    ResultadoProva.aluno_id == aluno_id, ResultadoProva.prova_id == prova.id
                )
            )
            if resultado is None:
                continue
            presente = presente or resultado.presente
            notas[materia] = resultado.nota or 0.0
        if notas:
            saida.append(CicloDoAluno(ciclo=ciclo, notas=notas, presente=presente))
    return saida


def regularidade(trajeto: list[CicloDoAluno]) -> float | None:
    """Desvio-padrao POPULACIONAL da media geral (confere com o 0,73 do Murilo)."""
    gerais = [c.geral for c in trajeto if c.presente]
    return statistics.pstdev(gerais) if len(gerais) > 1 else None


def aproveitamento_por_nivel(
    s: Session, aluno_id: int, ciclos: range | None = None
) -> dict[tuple[str, str], tuple[float, float]]:
    """(materia, nivel) -> (acerto do aluno, acerto da turma), ambos em %."""
    saida: dict[tuple[str, str], tuple[list[float], list[float]]] = {}

    for ciclo in ciclos or range(1, 6):
        for materia in rules.MATERIAS_PRIMEIRA_FASE:
            prova = obter_prova(s, ciclo, Fase.PRIMEIRA, materia)
            if prova is None:
                continue
            quadro = desempenho(s, prova)
            do_aluno = next((a for a in quadro.presentes if a.aluno_id == aluno_id), None)
            if do_aluno is None:
                continue
            for questao in quadro.questoes:
                if not questao.nivel:
                    continue
                chave = (materia, questao.nivel)
                aluno_notas, turma_notas = saida.setdefault(chave, ([], []))
                aluno_notas.append(
                    do_aluno.notas_por_questao.get(questao.numero, 0.0) / prova.nota_maxima_questao * 100
                )
                turma_notas.append(questao.acerto_pct)

    return {
        chave: (statistics.mean(aluno), statistics.mean(turma))
        for chave, (aluno, turma) in saida.items()
        if aluno
    }
