"""Relatorio de faltas — o "template B" dos relatorios originais.

Tipografia maior, separador "|" no lugar do "·", numero de pagina no cabecalho e
classificacao de uso interno. E um documento de direcao, nao de sala de aula.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.analytics import rules as R
from app.analytics.faltas import Panorama, panorama
from app.charts import svg as charts
from app.charts.svg import Coluna, colunas_verticais
from app.models import Fase, Materia
from app.reports.base import (
    CORPO, LARGURA_UTIL, MARGEM, Documento, Rodape, encurtar_nome,
)

SEPARADOR = "   |   "


@dataclass
class Relatorio:
    panorama: Panorama
    textos: dict[str, str] = field(default_factory=dict)

    @property
    def disciplina(self) -> str:
        return self.panorama.materia.value


TEXTOS_PADRAO = {
    "IMPACTO": (
        "Cada ciclo perdido é um diagnóstico individual que deixa de existir: sem a prova, "
        "não há como saber em que frente o aluno trava nem comparar sua evolução com a da "
        "turma. A ausência também contamina a métrica coletiva, porque as estatísticas "
        "passam a descrever apenas quem compareceu."
    ),
    "ENCAMINHAMENTOS": (
        "Apurar o motivo de cada ausência dos dois últimos ciclos. "
        "Revisar o dia e o horário de aplicação, verificando conflito com a grade da escola "
        "regular. Instituir reposição da prova para quem faltou. "
        "Acompanhar individualmente os casos de reincidência. "
        "Comunicar à turma o peso do simulado na preparação."
    ),
}


def montar(s: Session, materia: Materia, fase: Fase, textos: dict[str, str] | None = None) -> Relatorio:
    quadro = panorama(s, materia, fase)
    conteudo = dict(TEXTOS_PADRAO)
    conteudo.update({k: v for k, v in (textos or {}).items() if v and v.strip()})
    return Relatorio(quadro, conteudo)


def gerar(relatorio: Relatorio) -> bytes:
    p = relatorio.panorama
    faixa_ciclos = f"Ciclos {p.ciclos[0]} a {p.ciclos[-1]}" if p.ciclos else "—"
    fase = "discursivos" if p.fase is Fase.SEGUNDA else "objetivos"

    doc = Documento(
        titulo=f"Relatório de faltas — simulados {fase} de {relatorio.disciplina.lower()}",
        subtitulo=f"Turma ITA 2026{SEPARADOR}{faixa_ciclos}",
        rodape=Rodape(
            "Madan — Educação de Alta Performance" + SEPARADOR + "Coordenação Turma ITA"
            + SEPARADOR + f"Base: correção dos simulados de {relatorio.disciplina.lower()}"
        ),
        turma="USO INTERNO — DIREÇÃO",
    )

    _panorama(doc, relatorio)
    _listas(doc, relatorio)
    _encaminhamentos(doc, relatorio)
    return doc.gerar()


def _panorama(doc: Documento, r: Relatorio) -> None:
    p = r.panorama
    y = doc.nova_pagina("PANORAMA GERAL")

    if p.pendentes:
        y = doc.rotulo(
            y,
            f"⚠  {p.pendentes} ausência{'s' if p.pendentes != 1 else ''} ainda "
            "aguardando revisão da coordenação — os números abaixo são provisórios.",
            tamanho=8, forte=True, cor_texto=charts.ATENCAO,
        ) + 4

    recentes = p.recentes
    ultimos = [
        (
            f"Ausência no ciclo {ciclo}",
            R.formatar_percentual(p.percentual(ciclo), 1),
            f"{p.por_ciclo.get(ciclo, 0)} de {p.turma} alunos ausentes",
        )
        for ciclo in recentes
    ]
    salto = p.salto
    y = doc.indicadores(
        y,
        [
            ("Faltas no ano", str(p.total), f"somando os {len(p.ciclos)} ciclos"),
            *ultimos,
            (
                f"Salto até o ciclo {p.ciclos[-1]}" if salto is not None else "Salto",
                R.formatar_sinal(salto, 0) + "%" if salto is not None else "—",
                f"média de {R.formatar(p.media_anterior, 1)} para "
                f"{R.formatar(p.media_recente, 1)} faltas por ciclo",
            ),
            (
                "Alunos faltantes",
                str(len(p.envolvidos)),
                f"nos dois últimos ciclos — {R.formatar_percentual(len(p.envolvidos) / p.turma * 100)} da turma"
                if p.turma else "",
            ),
        ],
    )

    y = doc.secao(
        y, "Evolução das faltas por ciclo",
        f"percentual da turma ausente no simulado de {r.disciplina.lower()}",
    )
    metade = len(p.ciclos) // 2
    colunas = [
        Coluna(
            f"CICLO {ciclo}",
            p.percentual(ciclo),
            f"{p.por_ciclo.get(ciclo, 0)} falta{'s' if p.por_ciclo.get(ciclo, 0) != 1 else ''}",
            R.formatar_percentual(p.percentual(ciclo), 1),
            cor=charts.ERRO if indice >= metade and p.percentual(ciclo) >= 30 else charts.AZUL,
        )
        for indice, ciclo in enumerate(p.ciclos)
    ]
    doc.grafico(y, colunas_verticais(colunas, largura=520, altura=210), escala=1.0)

    # coluna da direita: como as faltas se espalham
    x = MARGEM + 430
    topo = doc.rotulo(y, "COMO AS FALTAS SE DISTRIBUEM NA TURMA", x=x, tamanho=7.6,
                      forte=True, cor_texto=charts.NAVY) + 4
    for rotulo, quantidade in p.distribuicao:
        proporcao = quantidade / p.turma * 100 if p.turma else 0
        doc.rotulo(topo, rotulo, x=x, tamanho=8, cor_texto=charts.TINTA)
        doc._canvas.setFont(CORPO, 8)
        doc._canvas.drawRightString(
            x + 330, doc._y(topo + 8),
            f"{quantidade} aluno{'s' if quantidade != 1 else ''}  ({R.formatar_percentual(proporcao)})",
        )
        topo = doc.grafico(topo + 11, charts.barra_simples(proporcao, largura=330), x=x) + 3

    topo += 8
    topo = doc.rotulo(topo, "LEITURA DO DADO", x=x, tamanho=7.6, forte=True, cor_texto=charts.NAVY)
    doc.texto(topo, _leitura(p), x=x, largura=336, tamanho=8, entrelinha=10.6)


def _leitura(p: Panorama) -> str:
    if not p.ciclos:
        return ""
    pior = max(p.ciclos, key=lambda c: p.por_ciclo.get(c, 0))
    partes = [
        f"O ciclo {pior} concentra o maior número de ausências: "
        f"{p.por_ciclo.get(pior, 0)} de {p.turma} alunos."
    ]
    if p.salto is not None and p.salto > 0:
        partes.append(
            f"A média por ciclo passou de {R.formatar(p.media_anterior, 1)} nos primeiros "
            f"ciclos para {R.formatar(p.media_recente, 1)} nos dois últimos."
        )
    envolvidos = len(p.envolvidos)
    if envolvidos:
        partes.append(
            f"{envolvidos} alunos faltaram em pelo menos um dos dois últimos ciclos, "
            f"e {len(p.cronicos)} acumulam {R.REINCIDENCIA if hasattr(R, 'REINCIDENCIA') else 3} "
            "ou mais faltas no ano."
        )
    integral = len(p.presenca_integral)
    partes.append(f"{integral} alunos mantiveram presença integral.")
    return " ".join(partes)


def _listas(doc: Documento, r: Relatorio) -> None:
    p = r.panorama
    if not p.envolvidos:
        return
    y = doc.nova_pagina("ALUNOS AUSENTES NOS CICLOS RECENTES")

    cabecalhos = ["#", "Aluno", *[f"C{c}" for c in p.ciclos], "Total"]
    larguras = [16.0, 168.0, *[24.0] * len(p.ciclos), 32.0]
    alinhamento = "cl" + "c" * len(p.ciclos) + "r"

    def montar_linhas(grupo):
        return [
            [
                str(indice + 1),
                encurtar_nome(aluno.nome, 162.0),
                *["F" if aluno.faltas.get(c) else "–" for c in p.ciclos],
                str(aluno.total),
            ]
            for indice, aluno in enumerate(grupo)
        ]

    def pintar(linha, coluna, texto):
        if 2 <= coluna < 2 + len(p.ciclos) and texto == "F":
            return ("#f8e5e5", charts.ERRO)
        return None

    for titulo, grupo, explicacao in [
        (
            f"Prioridade 1 — ausentes nos dois últimos ciclos",
            p.prioridade_1,
            "perderam os dois simulados mais recentes",
        ),
        (
            f"Prioridade 2 — ausentes em um dos dois últimos",
            p.prioridade_2,
            "perderam um dos dois simulados mais recentes",
        ),
    ]:
        if not grupo:
            continue
        y = doc.secao(y, f"{titulo}  ({len(grupo)} alunos)", explicacao)
        y = doc.tabela(y, cabecalhos, montar_linhas(grupo), larguras,
                       alinhamento=alinhamento, pintar=pintar, altura_linha=13.0) + 12

    # coluna da direita: os tres grupos de acompanhamento
    x = MARGEM + 340
    topo = 76.0
    for titulo, grupo, nota in [
        (
            "REINCIDÊNCIA CRÔNICA",
            p.cronicos,
            "três ou mais faltas no ano: para estes, a prova discursiva é conteúdo não treinado",
        ),
        (
            "COMEÇARAM A FALTAR AGORA",
            p.comecaram_agora,
            "primeira ausência do ano nos dois últimos ciclos — o problema é recente",
        ),
        (
            "PRESENÇA INTEGRAL",
            p.presenca_integral,
            "grupo de referência: manteve a rotina em todos os ciclos",
        ),
    ]:
        topo = doc.rotulo(topo, f"{titulo}  ·  {len(grupo)} alunos", x=x, tamanho=7.6,
                          forte=True, cor_texto=charts.NAVY)
        topo = doc.texto(topo, nota, x=x, largura=LARGURA_UTIL - 340, tamanho=7,
                         cor_texto=charts.TINTA_3, entrelinha=9)
        nomes = ", ".join(
            f"{encurtar_nome(a.nome, 9999)} ({a.total}/{a.ciclos})"
            if a.total else encurtar_nome(a.nome, 9999)
            for a in grupo[:14]
        )
        if len(grupo) > 14:
            nomes += f" e mais {len(grupo) - 14}"
        topo = doc.texto(topo + 1, nomes or "—", x=x, largura=LARGURA_UTIL - 340,
                         tamanho=7.6, entrelinha=9.8) + 10


def _encaminhamentos(doc: Documento, r: Relatorio) -> None:
    y = doc.nova_pagina("IMPACTO E ENCAMINHAMENTOS")
    largura = (LARGURA_UTIL - 24) / 2

    y2 = doc.secao(y, "Por que cada falta pesa tanto")
    doc.texto(y2, r.textos.get("IMPACTO", ""), largura=largura, tamanho=8.4, entrelinha=11.4)

    x = MARGEM + largura + 24
    doc._canvas.saveState()
    doc.rotulo(y, "ENCAMINHAMENTOS PROPOSTOS", x=x, tamanho=8.4, forte=True, cor_texto=charts.NAVY)
    doc._canvas.restoreState()
    topo = y + 16
    for indice, item in enumerate(
        [t.strip() for t in r.textos.get("ENCAMINHAMENTOS", "").split(".") if t.strip()], start=1
    ):
        doc.rotulo(topo, f"{indice}.", x=x, tamanho=8.4, forte=True, cor_texto=charts.OURO)
        topo = doc.texto(topo, item + ".", x=x + 14, largura=largura - 14,
                         tamanho=8.4, entrelinha=11.4) + 5
