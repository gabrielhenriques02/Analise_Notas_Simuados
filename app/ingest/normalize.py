"""Reconciliacao de nomes de alunos.

A planilha tem 89 grafias para ~41 pessoas: acentos inconsistentes, caixa mista e
erros de digitacao reais. A normalizacao resolve a maior parte; o que sobra precisa
de uma tabela de apelidos, porque nao da para inferir com seguranca.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field

# Apelidos conhecidos, confirmados contra a planilha e os relatorios de referencia.
# Chave e valor ja em forma normalizada.
APELIDOS_CONHECIDOS: dict[str, str] = {
    "LUCAS EMANUEL GONCAVELS GUIMARAES": "LUCAS EMANUEL GONCALVES GUIMARAES",
    "MIGUEL GUISAN ABREU DE LIMA": "MIGUEL GUISAN ABREU LIMA",
}

# Quantas linhas um nome desconhecido precisa ter para ser tratado como aluno de
# verdade e nao como erro de digitacao. Augusto Fabrete tem 24 linhas em 4 abas e
# esta ausente do roster; Arthur Damasceno tem 1 linha em 1 aba.
MINIMO_LINHAS_ALUNO_REAL = 5

# Acima deste grau de semelhanca, sugerimos o nome do roster como provavel destino.
SEMELHANCA_MINIMA = 0.86


def normalizar_nome(bruto: object) -> str:
    """Maiuscula, sem acento, sem pontuacao solta e com espacos colapsados."""
    if bruto is None:
        return ""
    texto = unicodedata.normalize("NFKD", str(bruto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.replace("\t", " ").replace(" ", " ")
    texto = re.sub(r"[^\w\s]", " ", texto, flags=re.UNICODE)
    return re.sub(r"\s+", " ", texto).strip().upper()


def normalizar_rm(bruto: object) -> str | None:
    """O RM vem ora como numero, ora como string com TAB e zeros a esquerda."""
    if bruto is None:
        return None
    texto = re.sub(r"\D", "", str(bruto))
    return texto.lstrip("0") or None if texto else None


@dataclass
class Pendencia:
    """Nome que nao casou com o roster e precisa de decisao da coordenacao."""

    nome_normalizado: str
    grafias: set[str] = field(default_factory=set)
    linhas: int = 0
    abas: set[str] = field(default_factory=set)
    sugestao: str | None = None
    semelhanca: float = 0.0

    @property
    def tipo(self) -> str:
        """Diferencia aluno ausente do roster de provavel erro de digitacao."""
        if self.sugestao and self.semelhanca >= SEMELHANCA_MINIMA:
            return "provavel_apelido"
        if self.linhas >= MINIMO_LINHAS_ALUNO_REAL:
            return "provavel_aluno_novo"
        return "registro_avulso"

    @property
    def explicacao(self) -> str:
        return {
            "provavel_apelido": (
                f"Parece outra grafia de “{self.sugestao}” "
                f"({self.semelhanca:.0%} de semelhança)."
            ),
            "provavel_aluno_novo": (
                f"Tem {self.linhas} lançamentos em {len(self.abas)} aba(s), "
                "mas não está na lista de alunos. Provavelmente falta no roster."
            ),
            "registro_avulso": (
                f"Só {self.linhas} lançamento(s) em {len(self.abas)} aba(s). "
                "Pode ser digitação errada ou aluno de outra turma."
            ),
        }[self.tipo]


@dataclass
class Reconciliacao:
    reconhecidos: dict[str, str] = field(default_factory=dict)  # normalizado -> canonico
    pendencias: list[Pendencia] = field(default_factory=list)
    sem_dados: list[str] = field(default_factory=list)  # no roster, sem lancamento

    @property
    def total_reconhecidos(self) -> int:
        return len(set(self.reconhecidos.values()))

    @property
    def resolvida(self) -> bool:
        return not self.pendencias


class Reconciliador:
    """Casa as grafias da planilha com a turma, usando apelidos quando preciso.

    A turma e a uniao de duas fontes: a aba do roster e os alunos ja cadastrados no
    banco. A segunda e indispensavel — alunos que entraram depois (caso do Augusto
    Fabrete) nunca aparecem na aba, e sem isso os lancamentos deles seriam
    descartados em silencio a cada reimportacao.
    """

    def __init__(
        self,
        roster: list[str],
        apelidos: dict[str, str] | None = None,
        conhecidos: dict[str, str] | None = None,
        descartados: set[str] | None = None,
    ) -> None:
        self._canonico: dict[str, str] = {}
        for nome in roster:
            self._canonico[normalizar_nome(nome)] = str(nome).strip()
        # Alunos ja cadastrados prevalecem sobre a aba.
        for chave, nome in (conhecidos or {}).items():
            self._canonico[normalizar_nome(chave)] = str(nome).strip()

        # Nomes que a coordenacao decidiu descartar saem da turma e deixam de
        # aparecer como pendencia a cada importacao.
        self._descartados = {normalizar_nome(n) for n in (descartados or ())}
        for chave in self._descartados:
            self._canonico.pop(chave, None)

        self._apelidos = dict(APELIDOS_CONHECIDOS)
        if apelidos:
            self._apelidos.update({normalizar_nome(k): normalizar_nome(v) for k, v in apelidos.items()})

    def descartado(self, bruto: object) -> bool:
        return normalizar_nome(bruto) in self._descartados

    def resolver(self, bruto: object) -> str | None:
        """Devolve o nome canonico, ou None se o nome nao for reconhecido."""
        chave = normalizar_nome(bruto)
        if not chave or chave in self._descartados:
            return None
        if chave in self._canonico:
            return self._canonico[chave]
        destino = self._apelidos.get(chave)
        if destino and destino in self._canonico:
            return self._canonico[destino]
        return None

    def reconciliar(self, ocorrencias: dict[str, tuple[set[str], int, set[str]]]) -> Reconciliacao:
        """Processa todas as grafias encontradas.

        `ocorrencias` mapeia nome normalizado -> (grafias originais, nº de linhas, abas).
        """
        resultado = Reconciliacao()
        vistos: set[str] = set()

        for chave, (grafias, linhas, abas) in sorted(ocorrencias.items()):
            if chave in self._descartados:
                continue
            canonico = self.resolver(chave)
            if canonico:
                resultado.reconhecidos[chave] = canonico
                vistos.add(normalizar_nome(canonico))
                continue

            sugestao, semelhanca = self._sugerir(chave)
            resultado.pendencias.append(
                Pendencia(
                    nome_normalizado=chave,
                    grafias=set(grafias),
                    linhas=linhas,
                    abas=set(abas),
                    sugestao=sugestao,
                    semelhanca=semelhanca,
                )
            )

        resultado.sem_dados = sorted(
            self._canonico[k] for k in self._canonico.keys() - vistos
        )
        return resultado

    def _sugerir(self, chave: str) -> tuple[str | None, float]:
        candidatos = difflib.get_close_matches(chave, self._canonico.keys(), n=1, cutoff=0.7)
        if not candidatos:
            return None, 0.0
        melhor = candidatos[0]
        razao = difflib.SequenceMatcher(None, chave, melhor).ratio()
        return self._canonico[melhor], razao
