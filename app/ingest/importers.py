"""Grava a planilha no banco.

A importacao e idempotente: rodar de novo sobre o mesmo arquivo atualiza os
registros em vez de duplicar. Pendencias de nome nao bloqueiam o restante — elas
sao devolvidas no resumo para a coordenacao decidir.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingest import xlsx_reader
from app.ingest.normalize import Pendencia, Reconciliador, normalizar_nome
from app.models import (
    Aluno, ApelidoAluno, Falta, Fase, Importacao, Materia, Nivel, Prova, Questao,
    Resposta, ResultadoProva,
)

# Quantas questoes e qual a escala de cada prova.
FORMATO_PROVAS = {
    ("1ª FASE", "MATEMÁTICA"): (12, 1.0, 0),
    ("1ª FASE", "FÍSICA"): (12, 1.0, 12),
    ("1ª FASE", "QUÍMICA"): (12, 1.0, 24),
    ("1ª FASE", "INGLÊS"): (12, 1.0, 36),
    ("2ª FASE", "MATEMÁTICA"): (10, 10.0, 0),
    ("2ª FASE", "FÍSICA"): (10, 10.0, 0),
    ("2ª FASE", "QUÍMICA"): (10, 10.0, 0),
    ("2ª FASE", "PORTUGUÊS"): (15, 1.0, 0),
    ("2ª FASE", "REDAÇÃO"): (5, 2.0, 0),
}

# Materias que compoem a media geral da 1ª fase. Ingles entra no minimo por
# materia, mas nao na media (ver CLAUDE.md).
MATERIAS_MEDIA_GERAL = ("MATEMÁTICA", "FÍSICA", "QUÍMICA")

# So na 1ª fase: com 36 questoes objetivas, acertar menos que isso fica abaixo do
# que o acaso daria, entao a prova provavelmente nao foi feita. O ciclo 2 do Augusto
# Fabrete soma 0,83 — uma questao — e o relatorio de referencia o trata como
# ausencia. Na 2ª fase o criterio nao vale: nota 0,9 quer dizer que o aluno escreveu
# algo e ganhou parcial, e aplicar o mesmo limiar la levantava 121 suspeitas falsas.
LIMIAR_QUASE_ZERADA = 1.0


@dataclass
class ResumoImportacao:
    arquivo: str = ""
    sha256: str = ""
    alunos_criados: int = 0
    alunos_reconhecidos: int = 0
    provas: int = 0
    questoes: int = 0
    respostas: int = 0
    resultados: int = 0
    faltas_inferidas: int = 0
    pendencias: list[dict] = field(default_factory=list)
    sem_dados: list[str] = field(default_factory=list)

    def como_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False, indent=2)


def _sha256(caminho: Path) -> str:
    digest = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 16), b""):
            digest.update(bloco)
    return digest.hexdigest()


def _obter_ou_criar_aluno(s: Session, nome: str, no_roster: bool) -> Aluno:
    chave = normalizar_nome(nome)
    aluno = s.scalar(select(Aluno).where(Aluno.nome_normalizado == chave))
    if aluno is None:
        aluno = Aluno(nome_canonico=nome, nome_normalizado=chave, no_roster=no_roster)
        s.add(aluno)
        s.flush()
    return aluno


def _descartar_aluno(s: Session, nome: str) -> None:
    """Marca como inativo em vez de apagar, preservando o historico."""
    chave = normalizar_nome(nome)
    aluno = s.scalar(select(Aluno).where(Aluno.nome_normalizado == chave))
    if aluno is None:
        aluno = Aluno(nome_canonico=str(nome).strip(), nome_normalizado=chave, no_roster=False)
        s.add(aluno)
    aluno.ativo = False
    s.flush()


def _obter_ou_criar_prova(s: Session, ciclo: int, fase: str, materia: str) -> Prova | None:
    formato = FORMATO_PROVAS.get((fase, materia))
    if formato is None:
        return None
    n_questoes, maxima, offset = formato

    prova = s.scalar(
        select(Prova).where(
            Prova.ciclo == ciclo, Prova.fase == Fase(fase), Prova.materia == Materia(materia)
        )
    )
    if prova is None:
        prova = Prova(
            ciclo=ciclo,
            fase=Fase(fase),
            materia=Materia(materia),
            n_questoes=n_questoes,
            nota_maxima_questao=maxima,
            offset_numeracao=offset,
        )
        s.add(prova)
        s.flush()
        s.add_all(Questao(prova_id=prova.id, numero=n) for n in range(1, n_questoes + 1))
        s.flush()
    return prova


def _chave_metadados(fase: str, materia: str) -> tuple[str, ...]:
    """Nivel e frente usam chaves diferentes para 1ª e 2ª fase na planilha."""
    if fase == "1ª FASE":
        return (f"1ª FASE {materia}",)
    return (materia,)


def _aplicar_nivel_e_frente(s: Session, prova: Prova, planilha: xlsx_reader.Planilha) -> None:
    questoes = {q.numero: q for q in s.scalars(select(Questao).where(Questao.prova_id == prova.id))}
    for chave in _chave_metadados(prova.fase.value, prova.materia.value):
        for numero, nivel in planilha.niveis.get((prova.ciclo, chave), {}).items():
            if numero in questoes:
                questoes[numero].nivel = Nivel(nivel)
        for numero, frente in planilha.frentes.get((prova.ciclo, chave), {}).items():
            if numero in questoes:
                questoes[numero].frente = frente


def importar(
    s: Session,
    caminho: Path,
    *,
    usuario_id: int | None = None,
    apelidos_extra: dict[str, str] | None = None,
    alunos_a_criar: set[str] | None = None,
    alunos_a_descartar: set[str] | None = None,
) -> ResumoImportacao:
    """Le a planilha e grava tudo.

    `alunos_a_criar` libera pendencias aprovadas pela coordenacao; `alunos_a_descartar`
    marca nomes que nao pertencem a turma, que passam a ser ignorados para sempre.
    """
    planilha = xlsx_reader.ler(caminho)
    resumo = ResumoImportacao(arquivo=caminho.name, sha256=_sha256(caminho))

    apelidos = dict(apelidos_extra or {})
    for apelido in s.scalars(select(ApelidoAluno)):
        apelidos[apelido.nome_normalizado] = apelido.aluno.nome_normalizado

    # Alunos ja cadastrados entram na turma mesmo sem estar na aba do roster, e os
    # inativos saem dela. Sem isso, quem entrou depois perderia os lancamentos.
    conhecidos = {
        a.nome_normalizado: a.nome_canonico
        for a in s.scalars(select(Aluno).where(Aluno.ativo.is_(True)))
    }
    descartados = {
        a.nome_normalizado for a in s.scalars(select(Aluno).where(Aluno.ativo.is_(False)))
    }
    descartados |= {normalizar_nome(n) for n in (alunos_a_descartar or ())}

    reconciliador = Reconciliador(planilha.roster, apelidos, conhecidos, descartados)
    reconciliacao = reconciliador.reconciliar(planilha.ocorrencias_de_nomes())
    resumo.sem_dados = reconciliacao.sem_dados

    # Descarte explicito: o aluno fica no banco como inativo, para nao voltar a ser
    # criado pela aba do roster nem reaparecer como pendencia.
    for nome in alunos_a_descartar or ():
        _descartar_aluno(s, nome)

    # Alunos do roster (os descartados nao voltam)
    antes = s.scalar(select(Aluno.id).limit(1))
    for nome in planilha.roster:
        if reconciliador.descartado(nome):
            continue
        _obter_ou_criar_aluno(s, nome, no_roster=True)

    # Pendencias: so viram aluno quando a coordenacao aprova
    liberados = {normalizar_nome(n) for n in (alunos_a_criar or ())}
    aprovadas: dict[str, Aluno] = {}
    for pendencia in reconciliacao.pendencias:
        if pendencia.nome_normalizado in liberados:
            canonico = sorted(pendencia.grafias)[0]
            aprovadas[pendencia.nome_normalizado] = _obter_ou_criar_aluno(
                s, canonico, no_roster=False
            )
        else:
            resumo.pendencias.append(_pendencia_como_dict(pendencia))

    resumo.alunos_reconhecidos = reconciliacao.total_reconhecidos + len(aprovadas)
    resumo.alunos_criados = s.query(Aluno).count() if antes is None else len(aprovadas)

    # Provas, questoes e respostas
    cache_alunos: dict[str, Aluno | None] = {}
    provas_vistas: dict[tuple[int, str, str], Prova] = {}

    for linha in planilha.lancamentos:
        aluno = _resolver_aluno(s, linha.nome_normalizado, reconciliador, aprovadas, cache_alunos)
        if aluno is None:
            continue

        chave = (linha.ciclo, linha.fase, linha.materia)
        prova = provas_vistas.get(chave)
        if prova is None:
            prova = _obter_ou_criar_prova(s, linha.ciclo, linha.fase, linha.materia)
            if prova is None:
                continue
            _aplicar_nivel_e_frente(s, prova, planilha)
            provas_vistas[chave] = prova

        resumo.respostas += _gravar_respostas(s, aluno, prova, linha)
        resumo.resultados += _gravar_resultado(s, aluno, prova, linha)

    s.flush()
    resumo.provas = len(provas_vistas)
    resumo.questoes = s.query(Questao).count()
    resumo.faltas_inferidas = _inferir_faltas(s)

    s.add(
        Importacao(
            arquivo=resumo.arquivo,
            sha256=resumo.sha256,
            usuario_id=usuario_id,
            status="concluida" if not resumo.pendencias else "com_pendencias",
            resumo=resumo.como_json(),
        )
    )
    return resumo


def _pendencia_como_dict(p: Pendencia) -> dict:
    return {
        "nome": p.nome_normalizado,
        "grafias": sorted(p.grafias),
        "linhas": p.linhas,
        "tipo": p.tipo,
        "explicacao": p.explicacao,
        "sugestao": p.sugestao,
    }


def _resolver_aluno(s, chave, reconciliador, aprovadas, cache):
    if chave in cache:
        return cache[chave]
    if chave in aprovadas:
        cache[chave] = aprovadas[chave]
        return cache[chave]
    canonico = reconciliador.resolver(chave)
    aluno = (
        s.scalar(
            select(Aluno).where(
                Aluno.nome_normalizado == normalizar_nome(canonico), Aluno.ativo.is_(True)
            )
        )
        if canonico
        else None
    )
    cache[chave] = aluno
    return aluno


def _gravar_respostas(s: Session, aluno: Aluno, prova: Prova, linha) -> int:
    questoes = {q.numero: q for q in s.scalars(select(Questao).where(Questao.prova_id == prova.id))}
    existentes = {
        r.questao_id: r
        for r in s.scalars(
            select(Resposta).where(
                Resposta.aluno_id == aluno.id,
                Resposta.questao_id.in_([q.id for q in questoes.values()]),
            )
        )
    }
    gravadas = 0
    for numero, nota in linha.notas.items():
        questao = questoes.get(numero)
        if questao is None:
            continue
        resposta = existentes.get(questao.id)
        if resposta is None:
            s.add(Resposta(aluno_id=aluno.id, questao_id=questao.id, nota=nota))
        else:
            resposta.nota = nota
        gravadas += 1
    return gravadas


def _gravar_resultado(s: Session, aluno: Aluno, prova: Prova, linha) -> int:
    """A nota e sempre calculada; a coluna da planilha nunca e usada como verdade."""
    total = sum(linha.notas.values())
    if prova.materia is Materia.REDACAO:
        nota = linha.nota_final
    elif prova.objetiva:
        nota = total / prova.n_questoes * 10
    else:
        nota = total / prova.n_questoes

    resultado = s.scalar(
        select(ResultadoProva).where(
            ResultadoProva.aluno_id == aluno.id, ResultadoProva.prova_id == prova.id
        )
    )
    if resultado is None:
        s.add(ResultadoProva(aluno_id=aluno.id, prova_id=prova.id, nota=nota, presente=True))
    else:
        resultado.nota = nota
    return 1


def _inferir_faltas(s: Session) -> int:
    """Marca presenca e propoe faltas.

    A planilha nao tem coluna de falta. Na 1ª fase a ausencia se reconhece quando o
    aluno zera Mat+Fis+Qui do ciclo inteiro; na 2ª fase, quando zera a prova toda.
    Nada disso vira registro antes da coordenacao confirmar.
    """
    resultados = list(s.scalars(select(ResultadoProva)))
    provas = {p.id: p for p in s.scalars(select(Prova))}

    # Soma por (aluno, ciclo) nas materias que compoem a media geral da 1ª fase.
    soma_primeira: dict[tuple[int, int], float] = {}
    for r in resultados:
        prova = provas[r.prova_id]
        if prova.fase is Fase.PRIMEIRA and prova.materia.value in MATERIAS_MEDIA_GERAL:
            chave = (r.aluno_id, prova.ciclo)
            soma_primeira[chave] = soma_primeira.get(chave, 0.0) + (r.nota or 0.0)

    existentes = {(f.aluno_id, f.prova_id): f for f in s.scalars(select(Falta))}
    inferidas = 0

    for r in resultados:
        prova = provas[r.prova_id]
        if prova.fase is Fase.PRIMEIRA:
            soma = soma_primeira.get((r.aluno_id, prova.ciclo), 0.0)
        else:
            soma = r.nota or 0.0

        if soma <= 0:
            motivo = "prova_zerada"
        elif prova.fase is Fase.PRIMEIRA and soma < LIMIAR_QUASE_ZERADA:
            motivo = "quase_zerada"
        else:
            motivo = None

        # So a prova zerada tira o aluno da estatistica por conta propria; a quase
        # zerada e apenas uma suspeita levada a coordenacao.
        r.presente = motivo != "prova_zerada"
        if motivo is None:
            continue
        inferidas += 1
        existente = existentes.get((r.aluno_id, r.prova_id))
        if existente is None:
            s.add(
                Falta(
                    aluno_id=r.aluno_id,
                    prova_id=r.prova_id,
                    motivo_inferencia=motivo,
                    confirmada=None,  # aguardando a coordenacao
                )
            )
        else:
            existente.motivo_inferencia = motivo
    return inferidas
