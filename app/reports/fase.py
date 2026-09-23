"""Relatorio de desempenho de uma prova — 1ª ou 2ª fase, uma materia, um ciclo."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.analytics import metrics as M
from app.analytics import narrative as N
from app.analytics import rules as R
from app.charts import svg as charts
from app.charts.svg import Barra, Segmento
from app.models import Prova, Questao
from app.provas import servico
from app.reports.base import CORPO, FORTE, LARGURA_UTIL, MARGEM, Documento, Rodape

LINHAS_POR_METADE = 20   # a divisao em duas metades e o que segura a tabela numa pagina
LARGURA_NOME = 118.0
# Os recortes sao renderizados a 150 dpi: cada ponto do PDF original vale
# 150/72 pixels. Abaixo de 45% do tamanho natural o enunciado de 10pt cai para
# menos de 4,5pt no papel e deixa de ser legivel — foi o que aconteceu quando a
# folha de constantes de Quimica entrou junto da questao.
DPI_RECORTE = 150.0
ESCALA_MINIMA = 0.45
ALTURA_MAXIMA_ENUNCIADO = 240.0
FIM_DA_COLUNA = 545.0


def _em_pontos(pixels: float) -> float:
    return pixels * 72.0 / DPI_RECORTE


def _escala(imagem, largura_disponivel: float, altura_disponivel: float) -> float:
    return min(
        largura_disponivel / _em_pontos(imagem.largura),
        altura_disponivel / _em_pontos(imagem.altura),
        1.0,
    )


def encurtar_nome(nome: str, limite: float = LARGURA_NOME - 6, tamanho: float = 7.4) -> str:
    """Abrevia os nomes do meio em vez de cortar no meio de uma palavra.

    "Maria Eduarda do Nascimento Ziebell" vira "Maria E. do N. Ziebell", que ainda
    identifica a pessoa — "Maria Eduarda Do Nascimen" nao identifica nem cabe.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    from app.reports.base import CORPO

    partes = nome.title().split()
    if not partes:
        return nome
    minusculas = {"Da", "De", "Do", "Das", "Dos", "E"}
    partes = [p if p not in minusculas else p.lower() for p in partes]

    def largura(texto: str) -> float:
        return stringWidth(texto, CORPO, tamanho)

    atual = " ".join(partes)
    meio = 1
    while largura(atual) > limite and meio < len(partes) - 1:
        parte = partes[meio]
        if parte.lower() not in {p.lower() for p in minusculas}:
            partes[meio] = parte[0] + "."
        meio += 1
        atual = " ".join(partes)

    while largura(atual) > limite and len(partes) > 2:
        del partes[1]
        atual = " ".join(partes)
    return atual

NIVEL_CORES = {
    "FÁCIL": ("#e1f1e7", "#17613d"),
    "MÉDIO": ("#e8ebf0", charts.NAVY),
    "DIFÍCIL": ("#e0e4ea", charts.NAVY),
}


@dataclass
class Relatorio:
    prova: Prova
    quadro: M.DesempenhoProva
    variacao: float | None
    media_anterior: float | None
    serie: list[float | None]
    textos: dict[str, str] = field(default_factory=dict)
    # questao_id -> (imagem da questao, imagem com o texto de apoio ou None)
    enunciados: dict[int, tuple] = field(default_factory=dict)
    sem_apoio: set[int] = field(default_factory=set)

    @property
    def objetiva(self) -> bool:
        return self.prova.objetiva


def montar(s: Session, prova: Prova, textos: dict[str, str] | None = None) -> Relatorio:
    quadro = M.desempenho(s, prova)
    variacao, media_anterior = M.variacao_entre_ciclos(s, prova.ciclo, prova.fase, prova.materia)
    serie = M.serie_de_medias(s, prova.fase, prova.materia)

    anterior_prova = M.obter_prova(s, prova.ciclo - 1, prova.fase, prova.materia)
    anterior = M.desempenho(s, anterior_prova) if anterior_prova else None

    gerados = N.blocos(quadro, variacao, serie, anterior)
    gerados.update({k: v for k, v in (textos or {}).items() if v and v.strip()})

    ids = {q.numero: q.id for q in s.query(Questao).filter(Questao.prova_id == prova.id)}
    for estatistica in quadro.questoes:
        estatistica.id = ids.get(estatistica.numero)

    enunciados, sem_apoio = {}, set()
    for estatistica in quadro.questoes_para_revisar:
        questao = s.get(Questao, estatistica.id) if estatistica.id else None
        if questao is None:
            continue
        sozinha = servico.imagem_da_questao(s, questao)
        if sozinha is None:
            continue
        com_apoio = servico.imagem_da_questao(s, questao, com_apoio=True)
        enunciados[questao.id] = (sozinha, com_apoio if com_apoio is not sozinha else None)

    return Relatorio(prova, quadro, variacao, media_anterior, serie, gerados, enunciados, sem_apoio)


def gerar(relatorio: Relatorio) -> bytes:
    prova, quadro = relatorio.prova, relatorio.quadro
    fase = prova.fase.value
    materia = prova.materia.value

    if relatorio.objetiva:
        faixa = (
            f"questões {1 + prova.offset_numeracao} a "
            f"{prova.n_questoes + prova.offset_numeracao} da prova"
        )
    else:
        faixa = (
            f"prova discursiva, {prova.n_questoes} questões "
            f"(0–{prova.nota_maxima_questao:.0f} cada)"
        )

    doc = Documento(
        titulo=f"Relatório de desempenho — {materia}",
        subtitulo=(
            f"Ciclo {prova.ciclo} — {fase}  ·  {faixa}  ·  "
            f"{len(quadro.presentes)} alunos avaliados de {quadro.total_matriculados} matriculados"
        ),
        rodape=Rodape(
            "Madan — Educação de Alta Performance  ·  Turma ITA 2026  ·  "
            f"Ciclo {prova.ciclo} — {fase}"
        ),
    )

    y = doc.nova_pagina("CLASSIFICAÇÃO DA TURMA")
    y = _indicadores(doc, relatorio, y)
    y = _grade(doc, relatorio, y)
    _comentarios(doc, relatorio, y)

    y = doc.nova_pagina("NÍVEL E ÍNDICE DE ERRO POR QUESTÃO")
    y = _questoes(doc, relatorio, y)
    _aproveitamento(doc, relatorio, y)

    _enunciados(doc, relatorio)
    return doc.gerar()


def _indicadores(doc: Documento, r: Relatorio, y: float) -> float:
    q = r.quadro
    corte = R.config.corte_materia
    nota_media = f"corte da disciplina: {R.formatar(corte)}"
    if not r.objetiva and q.mediana is not None:
        nota_media += f"  ·  mediana {R.formatar(q.mediana)}"

    revisar = q.questoes_para_revisar
    faceis = sum(1 for x in revisar if x.nivel == "FÁCIL")
    medias = sum(1 for x in revisar if x.nivel == "MÉDIO")

    return doc.indicadores(
        y,
        [
            (f"Média da turma em {r.prova.materia.value.lower()}", R.formatar(q.media), nota_media),
            (
                f"Variação vs. ciclo {r.prova.ciclo - 1}",
                R.formatar_sinal(r.variacao),
                f"Ciclo {r.prova.ciclo - 1}: {R.formatar(r.media_anterior)}"
                if r.media_anterior is not None
                else "sem ciclo anterior",
            ),
            (
                "Acima do corte",
                f"{q.acima_do_corte}/{len(q.presentes)}",
                f"{R.formatar_percentual(q.percentual_acima_do_corte)} dos presentes",
            ),
            ("Média dos 5 melhores", R.formatar(q.media_top), f"maior nota: {R.formatar(q.maior_nota)}"),
            (
                "Questões com erro ≥ 50%",
                str(len(revisar)),
                f"{faceis} de nível fácil  ·  {medias} de nível médio",
            ),
        ],
    )


def _grade(doc: Documento, r: Relatorio, y: float) -> float:
    """Acertos de cada aluno por questao, em duas metades lado a lado."""
    q, prova = r.quadro, r.prova
    legenda = (
        "✓ acerto, ✗ erro  ·  faixa vermelha à esquerda = abaixo do corte"
        if r.objetiva
        else f"0 a {prova.nota_maxima_questao:.0f} por questão  ·  o número é sempre a fonte da leitura"
    )
    y = doc.secao(y, f"{'Acertos' if r.objetiva else 'Nota'} de cada aluno por questão", legenda)

    numeros = [str(x.numero_no_caderno) for x in q.questoes]
    cabecalhos = ["#", "Aluno", *numeros, "Nota"]
    largura_celula = 14.0
    larguras = [15.0, LARGURA_NOME, *[largura_celula] * len(numeros), 30.0]
    alinhamento = "cl" + "c" * len(numeros) + "r"

    linhas_alunos = [
        [
            str(indice + 1),
            encurtar_nome(aluno.nome),
            *[_celula(aluno, x, prova, r.objetiva) for x in q.questoes],
            R.formatar(aluno.nota),
        ]
        for indice, aluno in enumerate(q.presentes)
    ]

    def pintar(linha_i, coluna_i, texto):
        if coluna_i < 2 or coluna_i == len(cabecalhos) - 1:
            return None
        return _cor_celula(texto, r.objetiva, prova.nota_maxima_questao)

    corte = R.config.corte_materia
    metades = [
        linhas_alunos[:LINHAS_POR_METADE],
        linhas_alunos[LINHAS_POR_METADE : LINHAS_POR_METADE * 2],
    ]
    largura_bloco = sum(larguras)
    fim = y
    for indice, metade in enumerate(metades):
        if not metade:
            continue
        deslocamento = indice * LINHAS_POR_METADE

        def abaixo_do_corte(numero, base=deslocamento):
            return q.presentes[base + numero].nota <= corte

        x = MARGEM + indice * (largura_bloco + 20)
        fim = max(
            fim,
            doc.tabela(y, cabecalhos, metade, larguras, x=x, alinhamento=alinhamento,
                       pintar=pintar, marcar=abaixo_do_corte, altura_linha=11.5),
        )

    if q.ausentes:
        fim = doc.texto(
            fim + 5,
            "Ausentes, não realizaram a prova e não entram em nenhuma estatística: "
            + ", ".join(encurtar_nome(n, limite=9999) for n in q.ausentes)
            + ".",
            tamanho=6.8, entrelinha=8.4,
        )
    return fim + 8


def _celula(aluno, estatistica, prova, objetiva: bool) -> str:
    nota = aluno.notas_por_questao.get(estatistica.numero, 0.0)
    if objetiva:
        return "✓" if nota >= prova.nota_maxima_questao else "✗"
    return f"{nota:.0f}"


def _cor_celula(texto: str, objetiva: bool, maxima: float) -> tuple[str, str]:
    if objetiva:
        return ("#2e8b57", "#ffffff") if texto == "✓" else ("#f8e5e5", "#c83434")
    try:
        nota = float(texto)
    except ValueError:
        return ("", charts.TINTA)
    if nota >= maxima:
        return ("#2e8b57", "#ffffff")
    if nota >= maxima / 2:
        return ("#7bc49c", "#123f2a")
    if nota > 0:
        return ("#feefdd", "#8c5108")
    return ("#f8e5e5", "#c83434")


def _comentarios(doc: Documento, r: Relatorio, y: float) -> None:
    blocos = list(r.textos.items())
    if not blocos:
        return
    colunas = 3
    largura = (LARGURA_UTIL - 24) / colunas
    for indice, (titulo, texto) in enumerate(blocos[:6]):
        coluna, linha = indice % colunas, indice // colunas
        x = MARGEM + coluna * (largura + 12)
        topo = y + linha * 46
        doc.rotulo(topo, titulo, x=x, tamanho=7, forte=True, cor_texto=charts.NAVY)
        doc.texto(topo + 11, texto, x=x, largura=largura, tamanho=6.9, entrelinha=8.6)


def _questoes(doc: Documento, r: Relatorio, y: float) -> float:
    q = r.quadro
    y = doc.secao(
        y,
        f"Nível, frente e índice de erro de cada questão — {r.prova.materia.value}",
        "CRÍTICA = questão fácil com acerto < 50%  ·  ATENÇÃO = média ou difícil com acerto < 50%",
    )

    cabecalhos = ["Questão", "Frente", "Nível", "Média", "Acerto", "Erro", "Alerta"]
    larguras = [46.0, 40.0, 52.0, 42.0, 44.0, 40.0, 54.0]
    alinhamento = "cccrrrc"
    linhas = [
        [
            f"Q{x.numero_no_caderno}",
            x.frente or "—",
            x.nivel or "—",
            R.formatar(x.media) if not r.objetiva else f"{x.acertos}/{x.presentes}",
            R.formatar_percentual(x.acerto_pct, 1),
            R.formatar_percentual(x.erro_pct),
            x.alerta.value or "—",
        ]
        for x in q.questoes
    ]

    def pintar(linha_i, coluna_i, texto):
        if coluna_i == 2 and texto in NIVEL_CORES:
            return NIVEL_CORES[texto]
        if coluna_i == 6:
            if texto == "CRÍTICA":
                return ("#f8e5e5", "#c83434")
            if texto == "ATENÇÃO":
                return ("#feefdd", "#8c5108")
        return None

    # As barras ficam ao lado da tabela e usam o MESMO passo de linha, para cada
    # barra ficar na altura da sua questao. O svglib converte px em pt (fator .75),
    # entao o passo aqui e o da tabela dividido por esse fator.
    altura_linha = 13.0
    passo_svg = round(altura_linha / 0.75)
    escala = altura_linha / (passo_svg * 0.75)

    x_barras = MARGEM + sum(larguras) + 16
    # Na mesma altura do cabecalho da tabela: acima colidiria com a legenda da secao.
    doc.rotulo(y + 1, "ÍNDICE DE ERRO", x=x_barras, tamanho=6.8, forte=True)
    fim_tabela = doc.tabela(
        y, cabecalhos, linhas, larguras, alinhamento=alinhamento, pintar=pintar,
        altura_linha=altura_linha,
    )
    fim_barras = doc.grafico(
        y + 13,
        charts.barras_horizontais(
            [
                Barra(
                    f"Q{x.numero_no_caderno}",
                    x.erro_pct,
                    cor=charts.ERRO if x.alerta is R.Alerta.CRITICA
                    else charts.ATENCAO if x.alerta is R.Alerta.ATENCAO
                    else charts.AZUL,
                )
                for x in q.questoes
            ],
            largura=300, largura_rotulo=34, passo=passo_svg,
        ),
        x=x_barras, escala=escala,
    )
    fim = max(fim_tabela, fim_barras)

    if not r.objetiva:
        x_dist = x_barras + 250
        doc.rotulo(y + 1, "DISTRIBUIÇÃO DAS CORREÇÕES", x=x_dist, tamanho=6.8, forte=True)
        topo = y + 13
        for x in q.questoes:
            doc.grafico(
                topo + 1.5,
                charts.barra_empilhada(
                    [
                        Segmento("nota máxima", x.maxima, charts.ACERTO),
                        Segmento("parcial ≥ 50%", x.parcial_alta, charts.PARCIAL),
                        Segmento("parcial < 50%", x.parcial_baixa, charts.ATENCAO),
                        Segmento("zerada", x.zerada, charts.ERRO),
                    ],
                    largura=200,
                ),
                x=x_dist,
            )
            topo += altura_linha
        fim = max(fim, topo)
        doc.rotulo(
            fim + 2,
            "nota máxima  ·  parcial ≥ 50%  ·  parcial < 50%  ·  questão zerada",
            x=x_dist, tamanho=6.4,
        )
    return fim + 16


def _aproveitamento(doc: Documento, r: Relatorio, y: float) -> float:
    rotulo = "% de acerto" if r.objetiva else "% de aproveitamento"
    y = doc.secao(y, "Aproveitamento por frente e por nível de dificuldade")

    frentes = [Barra(g.rotulo, g.aproveitamento, f"({g.questoes} q.)") for g in r.quadro.por_frente()]
    niveis = [Barra(g.rotulo, g.aproveitamento, f"({g.questoes} q.)") for g in r.quadro.por_nivel()]

    doc.rotulo(y, f"FRENTES DE {r.prova.materia.value}", tamanho=6.8, forte=True)
    fim_esquerda = doc.grafico(
        y + 11, charts.barras_horizontais(frentes, largura=340, rotulo_coluna=rotulo.upper())
    )

    x2 = MARGEM + 380
    doc.rotulo(y, "NÍVEL DE DIFICULDADE", x=x2, tamanho=6.8, forte=True)
    fim_direita = doc.grafico(
        y + 11,
        charts.barras_horizontais(niveis, largura=340, rotulo_coluna=rotulo.upper()),
        x=x2,
    )
    return max(fim_esquerda, fim_direita) + 8


def _enunciados(doc: Documento, r: Relatorio) -> None:
    """Os enunciados das questoes a revisar, dois por linha."""
    revisar = [x for x in r.quadro.questoes_para_revisar if x.id in r.enunciados]
    if not revisar:
        return

    largura = (LARGURA_UTIL - 18) / 2
    titulo = "Enunciados das questões com erro ≥ 50%"

    def abrir() -> list[float]:
        topo = doc.nova_pagina(titulo.upper(), compacto=True)
        topo = doc.secao(topo, titulo, "prioridade de revisão em sala, da pior para a melhor")
        return [topo, topo]

    y_coluna = abrir()

    for estatistica in revisar:
        sozinha, com_apoio = r.enunciados[estatistica.id]

        # Prefere mostrar o texto de apoio junto, mas so se o conjunto continuar
        # legivel; se nao couber, mostra a questao e avisa onde esta o apoio.
        imagem, avisar_apoio = sozinha, False
        if com_apoio is not None:
            if _escala(com_apoio, largura, ALTURA_MAXIMA_ENUNCIADO) >= ESCALA_MINIMA:
                imagem = com_apoio
            else:
                avisar_apoio = True

        escala = _escala(imagem, largura, ALTURA_MAXIMA_ENUNCIADO)
        largura_uso = largura
        # Enunciado que nao fica legivel em meia pagina ocupa a largura inteira.
        if escala < ESCALA_MINIMA and y_coluna[0] == y_coluna[1]:
            largura_uso = LARGURA_UTIL
            escala = _escala(imagem, largura_uso, ALTURA_MAXIMA_ENUNCIADO * 1.6)
        previsto = _em_pontos(imagem.altura) * escala + 30

        # sempre a coluna mais curta: as imagens tem alturas muito diferentes e
        # preencher em sequencia deixava metade da pagina vazia
        coluna = 0 if y_coluna[0] <= y_coluna[1] else 1
        if largura_uso > largura:
            coluna = 0
        if y_coluna[coluna] + previsto > FIM_DA_COLUNA:
            y_coluna = abrir()
            coluna = 0

        x = MARGEM + coluna * (largura + 18)
        topo = y_coluna[coluna]

        doc.rotulo(topo, f"Questão {estatistica.numero_no_caderno}", x=x,
                   tamanho=8, forte=True, cor_texto=charts.NAVY)
        deslocamento = x + 58
        if estatistica.nivel:
            deslocamento += doc.etiqueta(
                topo, deslocamento, estatistica.nivel,
                *NIVEL_CORES.get(estatistica.nivel, ("#e8ebf0", charts.NAVY)),
            )
        if estatistica.frente:
            deslocamento += doc.etiqueta(topo, deslocamento, estatistica.frente, "#eef1f6", charts.AZUL)
        if avisar_apoio:
            doc.etiqueta(topo, deslocamento, "USA A FOLHA DE APOIO", "#feefdd", "#8c5108")

        doc._canvas.setFont(CORPO, 7)
        doc._canvas.setFillColor(doc._canvas._fillColorObj)
        doc._canvas.drawRightString(
            x + largura_uso, doc._y(topo + 7),
            f"{R.formatar_percentual(estatistica.erro_pct)} de erro",
        )

        topo = doc.imagem(
            topo + 13, imagem.caminho, x=x, largura_max=largura_uso,
            altura_max=ALTURA_MAXIMA_ENUNCIADO * (1.6 if largura_uso > largura else 1.0),
        )
        if largura_uso > largura:
            y_coluna = [topo + 16, topo + 16]
        else:
            y_coluna[coluna] = topo + 16
