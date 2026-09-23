"""Sessao e metadados do banco."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import config


class Base(DeclarativeBase):
    pass


def _criar_engine():
    url = config.url_banco
    if url.startswith("sqlite"):
        config.dir_dados.mkdir(parents=True, exist_ok=True)
        motor = create_engine(url, future=True, connect_args={"check_same_thread": False})

        @event.listens_for(motor, "connect")
        def _ligar_chaves_estrangeiras(conexao, _):
            cursor = conexao.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return motor
    return create_engine(url, future=True, pool_pre_ping=True)


engine = _criar_engine()
Sessao = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def sessao() -> Iterator[Session]:
    """Sessao transacional: commita no sucesso, desfaz no erro."""
    s = Sessao()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def criar_tabelas() -> None:
    from app import models  # noqa: F401  (registra os modelos no metadata)

    Base.metadata.create_all(engine)
