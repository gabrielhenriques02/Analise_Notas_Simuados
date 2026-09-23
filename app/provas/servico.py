"""Liga o segmentador ao banco: guarda o PDF, grava os recortes, serve as imagens."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import config
from app.models import ArquivoProva, Prova, Questao, RecorteQuestao
from app.provas import segment
from app.provas.render import Imagem, renderizar
from app.provas.segment import Regiao


@dataclass
class ResumoProva:
    prova_id: int
    arquivo: str
    paginas: int
    questoes_no_pdf: int
    questoes_da_prova: int
    casadas: int
    apoios: int
    avisos: list[str]

    @property
    def completo(self) -> bool:
        return self.casadas == self.questoes_da_prova


def _sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def guardar_pdf(s: Session, prova: Prova, nome_original: str, dados: bytes) -> ArquivoProva:
    config.dir_provas.mkdir(parents=True, exist_ok=True)
    assinatura = _sha256(dados)
    destino = config.dir_provas / f"prova-{prova.id}-{assinatura[:12]}.pdf"
    destino.write_bytes(dados)

    registro = s.scalar(select(ArquivoProva).where(ArquivoProva.prova_id == prova.id))
    if registro is None:
        registro = ArquivoProva(prova_id=prova.id)
        s.add(registro)
    registro.nome_original = nome_original
    registro.arquivo = destino.name
    registro.sha256 = assinatura
    s.flush()
    return registro


def caminho_do_pdf(registro: ArquivoProva) -> Path:
    return config.dir_provas / registro.arquivo


def segmentar(s: Session, prova: Prova, registro: ArquivoProva) -> ResumoProva:
    """Roda o segmentador e grava um recorte por questao que casar.

    O numero no PDF da 1ª fase e o do caderno (Física começa em 13), enquanto a
    questao no banco e numerada de 1 a 12 dentro da materia — o offset faz a ponte.
    """
    caminho = caminho_do_pdf(registro)
    leitura = segment.ler(caminho)
    registro.paginas = leitura.paginas

    questoes = {
        q.numero + prova.offset_numeracao: q
        for q in s.scalars(select(Questao).where(Questao.prova_id == prova.id))
    }
    casadas = 0

    for proposta in leitura.recortes:
        questao = questoes.get(proposta.numero)
        if questao is None:
            continue
        recorte = s.scalar(
            select(RecorteQuestao).where(RecorteQuestao.questao_id == questao.id)
        )
        if recorte is None:
            recorte = RecorteQuestao(questao_id=questao.id)
            s.add(recorte)
        elif recorte.revisado:
            casadas += 1
            continue  # nao sobrescreve ajuste feito a mao

        recorte.regioes = json.dumps([[r.pagina, r.y0, r.y1] for r in proposta.regioes])
        recorte.apoio = (
            json.dumps([[r.pagina, r.y0, r.y1] for r in proposta.apoio.regioes])
            if proposta.apoio
            else None
        )
        recorte.apoio_descricao = proposta.apoio.descricao if proposta.apoio else None
        casadas += 1

    s.flush()
    return ResumoProva(
        prova_id=prova.id,
        arquivo=registro.nome_original,
        paginas=leitura.paginas,
        questoes_no_pdf=len(leitura.recortes),
        questoes_da_prova=len(questoes),
        casadas=casadas,
        apoios=len(leitura.apoios),
        avisos=leitura.avisos,
    )


def imagem_da_questao(
    s: Session, questao: Questao, *, com_apoio: bool = False
) -> Imagem | None:
    """Gera (ou reaproveita do cache) a imagem do enunciado."""
    recorte = s.scalar(select(RecorteQuestao).where(RecorteQuestao.questao_id == questao.id))
    if recorte is None:
        return None
    registro = s.scalar(
        select(ArquivoProva).where(ArquivoProva.prova_id == questao.prova_id)
    )
    if registro is None:
        return None

    regioes = [Regiao(p, y0, y1) for p, y0, y1 in recorte.regioes_lista]
    if com_apoio and recorte.apoio_lista:
        regioes = [Regiao(p, y0, y1) for p, y0, y1 in recorte.apoio_lista] + regioes
    if not regioes:
        return None

    return renderizar(
        caminho_do_pdf(registro), regioes, config.dir_cache_questoes / f"prova-{questao.prova_id}"
    )


def limpar_cache(prova_id: int) -> None:
    shutil.rmtree(config.dir_cache_questoes / f"prova-{prova_id}", ignore_errors=True)
