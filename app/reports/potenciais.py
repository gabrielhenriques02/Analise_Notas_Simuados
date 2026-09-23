"""Análise dos alunos com mais chance de aprovação.

Uma página de visão do grupo e uma por aluno. O que o sistema calcula é o
diagnóstico — onde cada um trava; a leitura e a prescrição ficam com a coordenação.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.analytics import rules as R
from app.analytics.potenciais import Dossie, cortes_do_grupo, destaques
from app.charts import svg as charts
from app.charts.svg import Barra, Referencia, Serie, barras_horizontais, linhas
from app.reports.base import (
    CORPO, FORTE, LARGURA_UTIL, MARGEM, Documento, Rodape, encurtar_nome,
)

NIVEIS = ("FÁCIL", "MÉDIO", "DIFÍCIL")


@dataclass
class Relatorio:
    grupo: list[Dossie]
    ciclos: list[int]
    textos: dict[str, str] = field(default_factory=dict)

    @property
    def provas_feitas(self) -> int:
        return sum(d.realizados for d in self.grupo)

    @property
    def cortes(self) -> dict[str, int]:
        return cortes_do_grupo(self.grupo)


def montar(s: Session, *, quantos: int = 8, ciclos: range | None = None,
           textos: dict[str, str] | None = None) -> Relatorio:
    faixa = ciclos or range(1, 6)
    grupo = destaques(s, quantos, faixa)
    return Relatorio(grupo, list(faixa), dict(textos or {}))


def gerar(relatorio: Relatorio) -> bytes:
    if not relatorio.grupo:
        raise ValueError("Nenhum aluno com prova realizada no período.")

    primeiro, ultimo = relatorio.ciclos[0], relatorio.ciclos[-1]
    corte_materia = R.formatar(R.config.corte_materia, 1)
    corte_geral = R.formatar(R.config.corte_geral, 1)

    doc = Documento(
        titulo="Análise individual — 1ª fase",
        subtitulo=(
            f"{len(relatorio.grupo)} alunos  ·  ciclos {primeiro} a {ultimo}  ·  "
            "os que estão mais perto da aprovação"
        ),
        rodape=Rodape(
            "Madan — Educação de Alta Performance  ·  Turma ITA 2026  ·  "
            f"corte: acima de {corte_materia} em cada matéria e acima de {corte_geral} "
            "em Mat+Fís+Quí"
        ),
    )

    _visao_do_grupo(doc, relatorio)
    for indice, dossie in enumerate(relatorio.grupo, start=1):
        _pagina_do_aluno(doc, relatorio, dossie, indice)
    return doc.gerar()


def _visao_do_grupo(doc: Documento, r: Relatorio) -> None:
    y = doc.nova_pagina("VISÃO DO GRUPO")

    cortes = r.cortes
    principais = list(cortes.items())[:3]
    y = doc.indicadores(
        y,
        [
            ("Alunos analisados", str(len(r.grupo)), "topo da Turma ITA 2026"),
            ("Provas de 1ª fase feitas", str(r.provas_feitas),
             f"{len(r.grupo)} alunos, menos as ausências"),
            ("Cortes por nota mínima", str(sum(cortes.values())),
             "por disciplina, não pela média"),
            *[
                (materia, str(quantidade),
                 "o eliminador nº 1 do grupo" if indice == 0 else f"{indice + 1}º maior motivo")
                for indice, (materia, quantidade) in enumerate(principais)
            ],
        ],
    )

    y_secao = doc.secao(y, "Por que eles são eliminados", "cortes por disciplina no período")
    doc.grafico(
        y_secao,
        barras_horizontais(
            [
                Barra(
                    R._abreviar(materia),
                    quantidade / max(cortes.values()) * 100,
                    cor=charts.ERRO,
                    texto=f"{quantidade} corte{'s' if quantidade != 1 else ''}",
                )
                for materia, quantidade in cortes.items()
            ],
            largura=300, largura_rotulo=40, largura_valor=56,
        ),
    )

    x = MARGEM + 330
    doc.rotulo(y_secao, "LEITURA DA COORDENAÇÃO", x=x, tamanho=7.6, forte=True,
               cor_texto=charts.NAVY)
    doc.texto(
        y_secao + 12,
        r.textos.get("GRUPO")
        or "Espaço reservado para a leitura da coordenação sobre o que estes números "
           "mostram em conjunto — o que se repete entre os alunos e o que fazer com isso.",
        x=x, largura=LARGURA_UTIL - 330, tamanho=7.8, entrelinha=10.4,
        cor_texto=charts.TINTA_2 if r.textos.get("GRUPO") else charts.TINTA_3,
    )

    y = y_secao + 92
    y = doc.secao(y, "Onde cada um deve investir primeiro")
    cabecalhos = ["Aluno", "Aprovações", "Travamento principal", "Segundo ponto", "Fáceis/prova"]
    larguras = [170.0, 62.0, 190.0, 190.0, 62.0]
    linhas_tabela = []
    for dossie in sorted(r.grupo, key=lambda d: (d.faceis_por_prova or 99)):
        trava = dossie.travamento
        segundo = dossie.segundo_ponto
        linhas_tabela.append(
            [
                encurtar_nome(dossie.nome, 164.0),
                f"{dossie.aprovacoes}/{dossie.realizados}",
                f"{trava.rotulo}: {R.formatar_percentual(trava.aproveitamento)} "
                f"({trava.acertos}/{trava.total})" if trava else "—",
                f"{segundo.rotulo}: {R.formatar_percentual(segundo.aproveitamento)} "
                f"({segundo.acertos}/{segundo.total})" if segundo else "—",
                R.formatar(dossie.faceis_por_prova, 1),
            ]
        )
    y = doc.tabela(y, cabecalhos, linhas_tabela, larguras, alinhamento="lclll".replace("l", "l", 1))
    doc.rotulo(
        y + 4,
        "Fáceis/prova = questões de nível fácil erradas em Mat+Fís+Quí, por prova realizada.  ·  "
        "Frentes com menos de 4 questões no período não entram no diagnóstico.",
        tamanho=6.8,
    )


def _pagina_do_aluno(doc: Documento, r: Relatorio, d: Dossie, indice: int) -> None:
    doc.titulo = d.nome.title()
    doc.subtitulo = d.veredito
    y = doc.nova_pagina(f"ALUNO {indice} DE {len(r.grupo)}")

    variacao = d.variacao_recente
    y = doc.indicadores(
        y,
        [
            ("Aprovações / provas feitas", f"{d.aprovacoes}/{d.realizados}",
             f"corte: >{R.formatar(R.config.corte_materia, 1)} por matéria e "
             f">{R.formatar(R.config.corte_geral, 1)} no geral"),
            ("Média geral", R.formatar(d.media_geral),
             f"melhor {R.formatar(d.melhor)}  ·  pior {R.formatar(d.pior)}"),
            ("Variação mais recente", R.formatar_sinal(variacao),
             "entre os dois últimos ciclos realizados"),
            ("Regularidade entre ciclos", R.formatar(d.regularidade),
             "desvio-padrão da média geral"),
            ("Fáceis perdidas por prova", R.formatar(d.faceis_por_prova, 1),
             f"{d.faceis_perdidas} questões fáceis em {d.provas_feitas} provas"),
        ],
    )

    esquerda_topo = doc.secao(y, "Trajetória nos ciclos")
    topo = esquerda_topo
    cabecalhos = ["Ciclo", "MAT", "FÍS", "QUÍ", "ING", "Geral", "Situação"]
    larguras = [34.0, 40.0, 40.0, 40.0, 40.0, 42.0, 150.0]
    linhas_tabela = []
    for ciclo in d.trajetoria:
        if not ciclo.presente:
            linhas_tabela.append(
                [str(ciclo.ciclo), "—", "—", "—", "—", "—", "ausente — não realizou"]
            )
            continue
        situacao = ciclo.situacao
        linhas_tabela.append(
            [
                str(ciclo.ciclo),
                *[R.formatar(ciclo.notas.get(m)) for m in
                  ("MATEMÁTICA", "FÍSICA", "QUÍMICA", "INGLÊS")],
                R.formatar(situacao.geral),
                f"{situacao.rotulo}" + (f"  ·  {situacao.motivo}" if situacao.motivo else ""),
            ]
        )

    def pintar(linha, coluna, texto):
        if coluna == 6:
            if texto.startswith("APROVADO"):
                return ("#e1f1e7", "#17613d")
            if texto.startswith("CORTADO"):
                return ("#f8e5e5", charts.ERRO)
        return None

    fim = doc.tabela(topo, cabecalhos, linhas_tabela, larguras, alinhamento="crrrrrl",
                     pintar=pintar)

    fim = doc.secao(fim + 10, "Evolução da média geral (Mat+Fís+Quí)")
    doc.grafico(
        fim,
        linhas(
            [Serie(d.nome, [c.geral if c.presente else None for c in d.trajetoria],
                   rotular_pontos=True)],
            [f"C{c.ciclo}" for c in d.trajetoria],
            largura=420, altura=170, maximo=10,
            referencias=[Referencia(R.config.corte_geral,
                                    f"corte {R.formatar(R.config.corte_geral, 1)}")],
        ),
    )

    # coluna da direita
    x = MARGEM + 420
    largura = LARGURA_UTIL - 420
    topo = doc.secao(esquerda_topo - 14, "Aproveitamento por nível",
                     "diferença para a média da turma", x=x)
    topo = _matriz_de_niveis(doc, d, topo, x, largura)

    topo = doc.secao(topo + 8, "Frentes mais fracas",
                     "mínimo de 4 questões no período", x=x)
    doc.grafico(
        topo,
        barras_horizontais(
            [
                Barra(f.rotulo, f.aproveitamento, f"({f.acertos}/{f.total})",
                      cor=charts.ERRO if f.aproveitamento < 40 else charts.ATENCAO)
                for f in d.frentes[:5]
            ],
            largura=int(largura) - 6, largura_rotulo=76,
        ),
        x=x,
    )

    chave = f"ALUNO:{d.aluno_id}"
    if r.textos.get(chave):
        doc.rotulo(486, "LEITURA DA COORDENAÇÃO", tamanho=7.6, forte=True, cor_texto=charts.NAVY)
        doc.texto(498, r.textos[chave], largura=LARGURA_UTIL, tamanho=8, entrelinha=10.6)


def _matriz_de_niveis(doc: Documento, d: Dossie, y: float, x: float, largura: float) -> float:
    """Materia x nivel, com a diferenca em pontos percentuais para a turma."""
    materias = ("MATEMÁTICA", "FÍSICA", "QUÍMICA", "INGLÊS")
    coluna = min(52.0, (largura - 52) / len(materias))
    canvas = doc._canvas

    canvas.setFont(FORTE, 6.6)
    canvas.setFillColor(charts.TINTA_3 and doc._canvas._fillColorObj)
    for indice, materia in enumerate(materias):
        canvas.setFont(FORTE, 6.6)
        canvas.drawCentredString(x + 54 + coluna * (indice + 0.5), doc._y(y + 7),
                                 R._abreviar(materia))
    y += 11

    for nivel in NIVEIS:
        doc.rotulo(y, nivel, x=x, tamanho=7, cor_texto=charts.TINTA_2)
        for indice, materia in enumerate(materias):
            par = d.niveis.get((materia, nivel))
            centro = x + 54 + coluna * (indice + 0.5)
            if par is None:
                canvas.setFont(CORPO, 7)
                canvas.drawCentredString(centro, doc._y(y + 8), "—")
                continue
            do_aluno, da_turma = par
            delta = do_aluno - da_turma
            canvas.setFont(FORTE, 8)
            canvas.drawCentredString(centro, doc._y(y + 8), R.formatar_percentual(do_aluno))
            canvas.setFont(CORPO, 6)
            canvas.drawCentredString(
                centro + 15, doc._y(y + 4), f"{'+' if delta >= 0 else '−'}{abs(delta):.0f}"
            )
        y += 13
    doc.rotulo(y, "número pequeno = diferença, em pontos percentuais, para a turma",
               x=x, tamanho=6.2)
    return y + 10
