"""Modelo de dados. Ver CLAUDE.md para as regras de negocio."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Fase(str, enum.Enum):
    PRIMEIRA = "1ª FASE"
    SEGUNDA = "2ª FASE"


class Materia(str, enum.Enum):
    MATEMATICA = "MATEMÁTICA"
    FISICA = "FÍSICA"
    QUIMICA = "QUÍMICA"
    INGLES = "INGLÊS"
    PORTUGUES = "PORTUGUÊS"
    REDACAO = "REDAÇÃO"


class Nivel(str, enum.Enum):
    """A planilha usa MÉDIO na 2ª fase e MÉDIA na 1ª; aqui vira um valor só."""

    FACIL = "FÁCIL"
    MEDIO = "MÉDIO"
    DIFICIL = "DIFÍCIL"


class Papel(str, enum.Enum):
    ADMIN = "admin"
    PROFESSOR = "professor"


class Aluno(Base):
    __tablename__ = "aluno"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome_canonico: Mapped[str] = mapped_column(String(160))
    nome_normalizado: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    rm: Mapped[str | None] = mapped_column(String(20))
    no_roster: Mapped[bool] = mapped_column(Boolean, default=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)

    apelidos: Mapped[list[ApelidoAluno]] = relationship(back_populates="aluno", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Aluno {self.nome_canonico}>"


class ApelidoAluno(Base):
    """Grafias alternativas do mesmo aluno (GONCALVES/GONCAVELS, ABREU LIMA/ABREU DE LIMA)."""

    __tablename__ = "apelido_aluno"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome_normalizado: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("aluno.id", ondelete="CASCADE"))
    origem: Mapped[str] = mapped_column(String(20), default="manual")  # manual | automatico

    aluno: Mapped[Aluno] = relationship(back_populates="apelidos")


class Prova(Base):
    __tablename__ = "prova"
    __table_args__ = (UniqueConstraint("ciclo", "fase", "materia", name="uq_prova"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ciclo: Mapped[int] = mapped_column(Integer, index=True)
    fase: Mapped[Fase] = mapped_column(Enum(Fase))
    materia: Mapped[Materia] = mapped_column(Enum(Materia))
    n_questoes: Mapped[int] = mapped_column(Integer)
    nota_maxima_questao: Mapped[float] = mapped_column(Float, default=1.0)
    # Deslocamento da numeracao no caderno: na 1ª fase, FÍSICA comeca na questao 13.
    offset_numeracao: Mapped[int] = mapped_column(Integer, default=0)

    questoes: Mapped[list[Questao]] = relationship(back_populates="prova", cascade="all, delete-orphan")

    @property
    def objetiva(self) -> bool:
        return self.nota_maxima_questao == 1.0


class Questao(Base):
    __tablename__ = "questao"
    __table_args__ = (UniqueConstraint("prova_id", "numero", name="uq_questao"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    prova_id: Mapped[int] = mapped_column(ForeignKey("prova.id", ondelete="CASCADE"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    nivel: Mapped[Nivel | None] = mapped_column(Enum(Nivel))
    frente: Mapped[str | None] = mapped_column(String(4))
    anulada: Mapped[bool] = mapped_column(Boolean, default=False)

    prova: Mapped[Prova] = relationship(back_populates="questoes")
    gabarito: Mapped[list[Gabarito]] = relationship(cascade="all, delete-orphan")

    @property
    def numero_no_caderno(self) -> int:
        return self.numero + self.prova.offset_numeracao


class Gabarito(Base):
    """Uma linha por alternativa correta: permite gabarito duplo (A/E)."""

    __tablename__ = "gabarito"
    __table_args__ = (UniqueConstraint("questao_id", "alternativa", name="uq_gabarito"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    questao_id: Mapped[int] = mapped_column(ForeignKey("questao.id", ondelete="CASCADE"), index=True)
    alternativa: Mapped[str] = mapped_column(String(1))


class Resposta(Base):
    __tablename__ = "resposta"
    __table_args__ = (UniqueConstraint("aluno_id", "questao_id", name="uq_resposta"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("aluno.id", ondelete="CASCADE"), index=True)
    questao_id: Mapped[int] = mapped_column(ForeignKey("questao.id", ondelete="CASCADE"), index=True)
    alternativa_marcada: Mapped[str | None] = mapped_column(String(1))
    nota: Mapped[float] = mapped_column(Float, default=0.0)


class ResultadoProva(Base):
    __tablename__ = "resultado_prova"
    __table_args__ = (UniqueConstraint("aluno_id", "prova_id", name="uq_resultado"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("aluno.id", ondelete="CASCADE"), index=True)
    prova_id: Mapped[int] = mapped_column(ForeignKey("prova.id", ondelete="CASCADE"), index=True)
    nota: Mapped[float | None] = mapped_column(Float)
    presente: Mapped[bool] = mapped_column(Boolean, default=True)


class Falta(Base):
    """Ausencia inferida da planilha, que so vale depois de confirmada."""

    __tablename__ = "falta"
    __table_args__ = (UniqueConstraint("aluno_id", "prova_id", name="uq_falta"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("aluno.id", ondelete="CASCADE"), index=True)
    prova_id: Mapped[int] = mapped_column(ForeignKey("prova.id", ondelete="CASCADE"), index=True)
    motivo_inferencia: Mapped[str] = mapped_column(String(40))  # prova_zerada | linha_ausente
    confirmada: Mapped[bool | None] = mapped_column(Boolean)  # None = aguardando coordenacao
    justificativa: Mapped[str | None] = mapped_column(Text)


class ClassificacaoPoliedro(Base):
    __tablename__ = "classificacao_poliedro"
    __table_args__ = (UniqueConstraint("aluno_id", "ciclo", "fase", name="uq_classificacao"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    aluno_id: Mapped[int] = mapped_column(ForeignKey("aluno.id", ondelete="CASCADE"), index=True)
    ciclo: Mapped[int] = mapped_column(Integer)
    fase: Mapped[Fase] = mapped_column(Enum(Fase))
    posicao: Mapped[int | None] = mapped_column(Integer)
    nota: Mapped[float | None] = mapped_column(Float)
    base_ranking: Mapped[int | None] = mapped_column(Integer)


class Usuario(Base):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(160))
    senha_hash: Mapped[str] = mapped_column(String(255))
    papel: Mapped[Papel] = mapped_column(Enum(Papel), default=Papel.PROFESSOR)
    materias: Mapped[str] = mapped_column(String(255), default="")  # separadas por virgula
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def materias_lista(self) -> list[str]:
        return [m for m in (p.strip() for p in self.materias.split(",")) if m]

    def pode_ver(self, materia: Materia | str) -> bool:
        if self.papel is Papel.ADMIN:
            return True
        valor = materia.value if isinstance(materia, Materia) else materia
        return valor in self.materias_lista


class Importacao(Base):
    __tablename__ = "importacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    arquivo: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    status: Mapped[str] = mapped_column(String(20), default="pendente")
    resumo: Mapped[str] = mapped_column(Text, default="{}")  # JSON


class Constante(Base):
    """Valores de negocio ajustaveis pela coordenacao (cortes, dados do ITA)."""

    __tablename__ = "constante"

    chave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[str] = mapped_column(String(120))
    descricao: Mapped[str] = mapped_column(String(255), default="")
