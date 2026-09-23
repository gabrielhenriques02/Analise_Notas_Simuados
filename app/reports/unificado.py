"""Relatorio unificado: a turma inteira, as duas fases, todos os ciclos."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.analytics import rules as R
from app.analytics.unificado import Unificado, faixa_da_posicao, montar as montar_dados
from app.charts import svg as charts
from app.charts.svg import Coluna, Referencia, Serie, colunas_verticais, linhas
from app.reports.base import (
    CORPO, FORTE, LARGURA_UTIL, MARGEM, Documento, Rodape, encurtar_nome,
)

CORES_DA_FAIXA = {
    "topo": ("#e1f1e7", "#17613d"),
    "meio": ("#feefdd", "#8c5108"),
    "fundo": ("#f8e5e5", charts.ERRO),
    "sem": ("", charts.TINTA_3),
}
DESTAQUES_NO_GRAFICO = 8


@dataclass
class Relatorio:
    dados: Unificado
    textos: dict[str, str] = field(default_factory=dict)


def montar(s: Session, ciclos: range | None = None, textos: dict[str, str] | None = None) -> Relatorio:
    return Relatorio(montar_dados(s, ciclos), dict(textos or {}))


def gerar(relatorio: Relatorio) -> bytes:
    d = relatorio.dados
    primeiro, ultimo = d.ciclos[0], d.ciclos[-1]

    doc = Documento(
        titulo=f"Relatório unificado dos simulados — ciclos {primeiro} a {ultimo}",
        subtitulo=(
            "Classificação da Turma ITA Madan no Sistema Poliedro  ·  1ª e 2ª fase  ·  2026"
        ),
        rodape=Rodape(
            "Madan — Educação de Alta Performance  ·  Turma ITA 2026  ·  "
            f"Ciclos {primeiro} a {ultimo}"
        ),
    )

    _panorama(doc, relatorio)
    _classificacao(doc, relatorio)
    _dificuldade(doc, relatorio)
    return doc.gerar()


def _panorama(doc: Documento, r: Relatorio) -> None:
    d = r.dados
    y = doc.nova_pagina("PANORAMA GERAL")

    if not d.tem_classificacao:
        y = doc.rotulo(
            y,
            "⚠  Nenhuma classificação do Sistema Poliedro importada — as colunas de "
            "ranking saem vazias. Importe as planilhas em Provas em PDF.",
            tamanho=8, forte=True, cor_texto=charts.ATENCAO,
        ) + 4
    elif len(d.com_classificacao) < len(d.ciclos):
        faltando = [c for c in d.ciclos if c not in d.com_classificacao]
        y = doc.rotulo(
            y,
            f"⚠  Classificação do Poliedro disponível apenas para o(s) ciclo(s) "
            f"{', '.join(map(str, d.com_classificacao))}. Sem dados dos ciclos "
            f"{', '.join(map(str, faltando))}, o ranking fica incompleto.",
            tamanho=8, forte=True, cor_texto=charts.ATENCAO,
        ) + 4

    melhor = d.melhor_do_periodo
    y = doc.indicadores(
        y,
        [
            (
                "Melhor classificação",
                R.formatar_ordinal(melhor[1]) if melhor else "—",
                f"{melhor[0].title().split()[0]} {melhor[0].title().split()[-1]}, ciclo {melhor[2]}"
                if melhor else "sem dados do Poliedro",
            ),
            ("Aprovações na 1ª fase", str(d.total_aprovados_1a),
             f"em {d.total_provas} provas realizadas"),
            ("Aprovações na 2ª fase", str(d.total_aprovados_2a),
             "passagens completas pelos dois cortes"),
            (
                f"No top {d.top}",
                str(max((l.no_top for l in d.linhas), default=0)),
                "melhor ciclo do período",
            ),
            ("Corte real do ITA", R.formatar(R.config.corte_ita),
             "referência da 1ª fase do vestibular"),
        ],
    )

    y = doc.secao(y, "Panorama por ciclo", "turma completa, 1ª e 2ª fase")
    cabecalhos = [
        "Ciclo", "Presentes", "Média", "Maior nota", f"≥ {R.formatar(R.config.corte_ita)}",
        "Aprov. 1ª", "Aprov. 2ª", "Melhor", "Mediana", f"Top {d.top}",
        "Dific. 1ª", "Dific. 2ª",
    ]
    larguras = [40.0, 56.0, 44.0, 56.0, 44.0, 48.0, 48.0, 48.0, 52.0, 44.0, 48.0, 48.0]
    linhas_tabela = [
        [
            f"Ciclo {l.ciclo}",
            f"{l.presentes}/{l.matriculados}",
            R.formatar(l.media),
            R.formatar(l.maior_nota),
            str(l.acima_do_corte_ita),
            str(l.aprovados_1a),
            str(l.aprovados_2a),
            R.formatar_ordinal(l.melhor_posicao),
            R.formatar_ordinal(l.mediana_posicao),
            str(l.no_top) if l.melhor_posicao else "—",
            R.formatar(l.indice_1a),
            R.formatar(l.indice_2a),
        ]
        for l in d.linhas
    ]
    y = doc.tabela(y, cabecalhos, linhas_tabela, larguras, alinhamento="l" + "r" * 11)
    y = doc.rotulo(
        y + 3,
        "Aprovações pelo critério do Sistema Poliedro.  ·  "
        f"Índice de dificuldade: {R.formatar(1.0)} = prova toda fácil, {R.formatar(3.0)} = toda difícil.",
        tamanho=6.8,
    )

    y = doc.secao(y + 8, "Média da turma e dificuldade da prova, ciclo a ciclo")
    colunas = [
        Coluna(
            f"CICLO {l.ciclo}", l.media or 0.0,
            R.formatar(l.media),
            f"{l.presentes} presentes",
            cor=charts.ACERTO if (l.media or 0) >= R.config.corte_geral else charts.AZUL,
        )
        for l in d.linhas
    ]
    # marcas=6 com teto 10 da passo 2 (0,2,4,6,8,10); com o padrao 5 o passo vira
    # 2,5 e as marcas saem arredondadas para 2 e 8, que e simplesmente errado.
    doc.grafico(
        y,
        colunas_verticais(colunas, largura=470, altura=200, maximo=10, sufixo="", marcas=6),
    )

    x = MARGEM + 470
    doc.rotulo(y, "LEITURA DA COORDENAÇÃO", x=x, tamanho=7.6, forte=True, cor_texto=charts.NAVY)
    doc.texto(
        y + 12,
        r.textos.get("PANORAMA")
        or "Espaço reservado para a leitura executiva do período — o que a série mostra "
           "sobre a evolução da turma e o que muda no plano do próximo ciclo.",
        x=x, largura=LARGURA_UTIL - 470, tamanho=7.8, entrelinha=10.4,
        cor_texto=charts.TINTA_2 if r.textos.get("PANORAMA") else charts.TINTA_3,
    )


def _classificacao(doc: Documento, r: Relatorio) -> None:
    d = r.dados
    if not d.tem_classificacao:
        return
    y = doc.nova_pagina("CLASSIFICAÇÃO NO SISTEMA POLIEDRO")
    y = doc.secao(
        y, "Classificação de todos os alunos da turma",
        f"posição no ranking da rede em cada ciclo, ordenada pela média das posições  ·  "
        f"verde = top {d.top}",
    )

    cabecalhos = ["#", "Aluno", *[f"Ciclo {c}" for c in d.ciclos], "Média", "Aprov. 1ª · 2ª"]
    larguras = [18.0, 150.0, *[44.0] * len(d.ciclos), 44.0, 64.0]
    alinhamento = "cl" + "r" * len(d.ciclos) + "rc"

    com_dados = [a for a in d.ranking if a.realizadas]
    sem_dados = [a for a in d.ranking if not a.realizadas]

    linhas_tabela = [
        [
            str(indice + 1),
            encurtar_nome(aluno.nome, 146.0),
            *[R.formatar_ordinal(aluno.posicoes.get(c)) for c in d.ciclos],
            R.formatar_ordinal(int(aluno.media_posicoes)) if aluno.media_posicoes else "—",
            f"{aluno.aprovacoes_1a} · {aluno.aprovacoes_2a}",
        ]
        for indice, aluno in enumerate(com_dados)
    ]

    def pintar(linha, coluna, texto):
        if 2 <= coluna < 2 + len(d.ciclos) and texto != "—":
            posicao = int(texto.rstrip("º"))
            return CORES_DA_FAIXA[faixa_da_posicao(posicao, d.top)]
        return None

    # Duas metades lado a lado so cabem se a tabela for estreita: com cinco ciclos
    # ela mede 496pt e duas nao entram nos 774pt uteis — a da direita saia cortada.
    largura_bloco = sum(larguras)
    cabe_em_duas = largura_bloco * 2 + 16 <= LARGURA_UTIL

    if cabe_em_duas:
        metade = (len(linhas_tabela) + 1) // 2
        blocos = [linhas_tabela[:metade], linhas_tabela[metade:]]
    else:
        larguras[1] = LARGURA_UTIL - (largura_bloco - larguras[1])
        blocos = [linhas_tabela]

    fim = y
    for indice, bloco in enumerate(blocos):
        if not bloco:
            continue
        fim = max(
            fim,
            doc.tabela(y, cabecalhos, bloco, larguras,
                       x=MARGEM + indice * (largura_bloco + 16),
                       alinhamento=alinhamento, pintar=pintar, altura_linha=11.0),
        )

    if sem_dados:
        fim = doc.texto(
            fim + 4,
            f"Sem classificação no período: "
            + ", ".join(encurtar_nome(a.nome, 9999) for a in sem_dados)
            + ".",
            tamanho=6.8, entrelinha=8.4,
        )

    doc.rotulo(fim + 4,
               f"Verde = top {d.top} da rede  ·  laranja = até {int(d.top * 1.8)}º  ·  "
               "vermelho = abaixo disso  ·  média calculada só sobre os ciclos realizados",
               tamanho=6.8)

    # trajetoria dos melhores, eixo invertido
    melhores = [a for a in com_dados if len(a.realizadas) >= 1][:DESTAQUES_NO_GRAFICO]
    if len(d.com_classificacao) < 2:
        return
    fim = doc.secao(fim + 14, "Trajetória no ranking geral do Poliedro",
                    "eixo invertido — mais alto é melhor")
    paleta = [charts.NAVY, charts.AZUL, charts.ACERTO, charts.ATENCAO,
              "#8c59a6", "#338c9e", "#b87333", "#596b87"]
    pior = max((p for a in melhores for p in a.realizadas), default=700)
    doc.grafico(
        fim,
        linhas(
            [
                Serie(aluno.nome.title().split()[0], [aluno.posicoes.get(c) for c in d.ciclos],
                      cor=paleta[indice % len(paleta)])
                for indice, aluno in enumerate(melhores)
            ],
            [f"C{c}" for c in d.ciclos],
            largura=700, altura=180, invertido=True, minimo=1, maximo=pior * 1.05,
            formatar=lambda v: f"{v:.0f}º",
            referencias=[Referencia(d.top, f"top {d.top} da rede", charts.ACERTO)],
            rotulos_a_direita=True,
        ),
    )


def _dificuldade(doc: Documento, r: Relatorio) -> None:
    d = r.dados
    y = doc.nova_pagina("DIFICULDADE × DESEMPENHO")
    y = doc.secao(
        y, "Nível das provas e resposta da turma",
        "o índice resume a composição da prova por nível cadastrado na planilha",
    )

    cabecalhos = ["Ciclo", "Índice 1ª fase", "Índice 2ª fase", "Média da turma",
                  "Presentes", "Acima do corte do ITA"]
    larguras = [50.0, 76.0, 76.0, 76.0, 60.0, 110.0]
    linhas_tabela = [
        [
            f"Ciclo {l.ciclo}",
            R.formatar(l.indice_1a),
            R.formatar(l.indice_2a),
            R.formatar(l.media),
            f"{l.presentes}/{l.matriculados}",
            f"{l.acima_do_corte_ita} aluno{'s' if l.acima_do_corte_ita != 1 else ''}",
        ]
        for l in d.linhas
    ]
    # guarda o topo da tabela: a caixa ao lado tem que comecar na mesma altura, e
    # nao num deslocamento fixo — com a tabela curta, y-190 caia fora da pagina.
    topo_da_tabela = y
    y = doc.tabela(y, cabecalhos, linhas_tabela, larguras, alinhamento="lrrrrr")

    x = MARGEM + 470
    doc.rotulo(topo_da_tabela, "COMO LER", x=x, tamanho=7.6, forte=True, cor_texto=charts.NAVY)
    doc.texto(
        topo_da_tabela + 12,
        "O índice de dificuldade pesa cada questão pelo nível cadastrado: 1,00 se a prova "
        "inteira fosse fácil, 3,00 se fosse toda difícil. Comparar a média da turma com o "
        "índice do ciclo separa a evolução real da variação de dificuldade da prova — uma "
        "média que sobe numa prova mais fácil não é o mesmo que uma média que sobe numa "
        "prova mais dura.",
        x=x, largura=LARGURA_UTIL - 470, tamanho=7.8, entrelinha=10.4,
    )

    y = doc.secao(y + 10, "Índice de dificuldade por ciclo", "1,00 = toda fácil  ·  3,00 = toda difícil")
    doc.grafico(
        y,
        linhas(
            [
                Serie("1ª fase", [l.indice_1a for l in d.linhas], cor=charts.NAVY,
                      rotular_pontos=True),
                Serie("2ª fase", [l.indice_2a for l in d.linhas], cor=charts.ATENCAO,
                      rotular_pontos=True),
            ],
            [f"C{l.ciclo}" for l in d.linhas],
            largura=440, altura=180, minimo=1.0, maximo=3.0,
            formatar=lambda v: R.formatar(v),
            rotulos_a_direita=True,
        ),
    )
