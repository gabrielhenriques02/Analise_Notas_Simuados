"""Textos gerados a partir dos numeros.

So o que da para derivar com seguranca. A leitura interpretativa — a que diz "o ganho
vem do topo da turma, nao da base" — fica para a coordenacao escrever no editor;
inventa-la aqui seria passar palpite por analise.
"""

from __future__ import annotations

from app.analytics import metrics as M
from app.analytics import rules as R


def _lista(nomes: list[str], limite: int = 6) -> str:
    primeiros = [n.split()[0].title() for n in nomes[:limite]]
    resto = len(nomes) - len(primeiros)
    texto = ", ".join(primeiros)
    return f"{texto} e mais {resto}" if resto > 0 else texto


def onde_a_turma_esta(quadro: M.DesempenhoProva, variacao: float | None, serie: list[float | None]) -> str:
    if quadro.media is None:
        return ""
    corte = R.config.corte_materia
    abaixo = len(quadro.presentes) - quadro.acima_do_corte
    partes = [f"Média {R.formatar(quadro.media)}"]
    if variacao is not None:
        partes[0] += f" ({R.formatar_sinal(variacao)} vs. o ciclo anterior)"
    partes[0] += "."
    partes.append(
        f"{quadro.acima_do_corte} de {len(quadro.presentes)} acima do corte de "
        f"{R.formatar(corte, 1)} — {abaixo} seria{'m' if abaixo != 1 else ''} "
        f"eliminado{'s' if abaixo != 1 else ''} só por esta prova."
    )
    valores = [R.formatar(m) for m in serie if m is not None]
    if len(valores) > 1:
        partes.append("Série dos ciclos: " + " · ".join(valores) + ".")
    return " ".join(partes)


def frentes_mais_fracas(quadro: M.DesempenhoProva) -> str:
    grupos = quadro.por_frente()
    if not grupos:
        return ""
    pior, melhor = grupos[0], grupos[-1]
    texto = (
        f"{pior.rotulo}: {R.formatar_percentual(pior.aproveitamento)} de acerto em "
        f"{pior.questoes} {'questão' if pior.questoes == 1 else 'questões'}."
    )
    if melhor is not pior:
        texto += f" Melhor frente: {melhor.rotulo} com {R.formatar_percentual(melhor.aproveitamento)}."
    faceis = next((n for n in quadro.por_nivel() if n.rotulo == "FÁCIL"), None)
    if faceis:
        texto += f" Nível fácil rendeu {R.formatar_percentual(faceis.aproveitamento)}."
    return texto


def o_que_revisar(quadro: M.DesempenhoProva) -> str:
    revisar = quadro.questoes_para_revisar
    if not revisar:
        return "Nenhuma questão fácil ou média ficou abaixo de 50% de acerto."
    faceis = [q for q in revisar if q.nivel == "FÁCIL"]
    numeros = ", ".join(f"Q{q.numero_no_caderno}" for q in revisar)
    texto = (
        f"{len(revisar)} {'questão' if len(revisar) == 1 else 'questões'} com erro ≥ 50% "
        f"({numeros})"
    )
    if faceis:
        pontos = len(faceis) * (10 / quadro.prova.n_questoes)
        texto += (
            f", sendo {len(faceis)} de nível fácil — pontos que a turma não pode perder "
            f"e que valem {R.formatar(pontos)} na nota."
        )
    else:
        texto += "."
    return texto + " Os enunciados estão nas páginas seguintes."


def acompanhamento(quadro: M.DesempenhoProva, anterior: M.DesempenhoProva | None) -> str:
    partes = []
    if anterior:
        antes = {a.aluno_id: a.nota for a in anterior.presentes}
        cairam = sorted(
            (a for a in quadro.presentes if a.aluno_id in antes and antes[a.aluno_id] - a.nota >= 2),
            key=lambda a: antes[a.aluno_id] - a.nota, reverse=True,
        )
        subiram = sorted(
            (a for a in quadro.presentes if a.aluno_id in antes and a.nota - antes[a.aluno_id] >= 2),
            key=lambda a: a.nota - antes[a.aluno_id], reverse=True,
        )
        if cairam:
            partes.append(f"Caíram 2 pontos ou mais: {_lista([a.nome for a in cairam])}.")
        if subiram:
            partes.append(f"Subiram 2 pontos ou mais: {_lista([a.nome for a in subiram])}.")
    if quadro.ausentes:
        n = len(quadro.ausentes)
        partes.append(
            f"{n} aluno{'s' if n != 1 else ''} {'faltaram' if n != 1 else 'faltou'} e "
            f"{'não entram' if n != 1 else 'não entra'} em nenhuma estatística."
        )
    return " ".join(partes)


def questoes_em_branco(quadro: M.DesempenhoProva) -> str:
    """So faz sentido na 2ª fase, onde da para nao iniciar a questao."""
    if quadro.prova.objetiva:
        return ""
    zeradas = sorted(quadro.questoes, key=lambda q: q.zerada, reverse=True)[:3]
    zeradas = [q for q in zeradas if q.zerada]
    if not zeradas:
        return ""
    itens = ", ".join(
        f"Q{q.numero_no_caderno} com {q.zerada} de {q.presentes} zerando "
        f"({R.formatar_percentual(q.zerada / q.presentes * 100)})"
        for q in zeradas
    )
    return (
        f"O maior problema não é o erro de conta, é a questão não iniciada: {itens}. "
        "Mesmo o desenvolvimento parcial pontua na 2ª fase."
    )


def blocos(
    quadro: M.DesempenhoProva,
    variacao: float | None,
    serie: list[float | None],
    anterior: M.DesempenhoProva | None,
) -> dict[str, str]:
    """Os textos que entram no relatorio, por titulo de bloco."""
    saida = {
        "ONDE A TURMA ESTÁ": onde_a_turma_esta(quadro, variacao, serie),
        "FRENTE MAIS FRÁGIL": frentes_mais_fracas(quadro),
        "ACOMPANHAMENTO INDIVIDUAL": acompanhamento(quadro, anterior),
        "O QUE REVISAR EM SALA": o_que_revisar(quadro),
    }
    em_branco = questoes_em_branco(quadro)
    if em_branco:
        saida["QUESTÕES EM BRANCO"] = em_branco
    return {titulo: texto for titulo, texto in saida.items() if texto}
