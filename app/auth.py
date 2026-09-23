"""Autenticacao por sessao assinada, com contas geridas pela coordenacao."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import config
from app.db import Sessao
from app.models import Materia, Papel, Usuario

COOKIE = "sessao"
VALIDADE = 60 * 60 * 12  # 12 horas

_hasher = PasswordHasher()


def _serializador() -> URLSafeTimedSerializer:
    if not config.chave_secreta or config.chave_secreta.startswith("troque"):
        raise RuntimeError(
            "SECRET_KEY não configurada. Gere uma com: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    return URLSafeTimedSerializer(config.chave_secreta, salt="sessao-simulados")


def cifrar(senha: str) -> str:
    return _hasher.hash(senha)


def conferir(senha: str, hash_guardado: str) -> tuple[bool, str | None]:
    """Devolve (confere, hash novo se precisar reescrever)."""
    try:
        _hasher.verify(hash_guardado, senha)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False, None
    novo = _hasher.hash(senha) if _hasher.check_needs_rehash(hash_guardado) else None
    return True, novo


def gerar_senha(tamanho: int = 12) -> str:
    """Senha inicial para uma conta nova, entregue pela coordenacao."""
    alfabeto = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alfabeto) for _ in range(tamanho))


# ── banco por requisicao ────────────────────────────────────────────────────────

def obter_sessao():
    s = Sessao()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ── login ───────────────────────────────────────────────────────────────────────

def autenticar(s: Session, email: str, senha: str) -> Usuario | None:
    usuario = s.scalar(
        select(Usuario).where(func.lower(Usuario.email) == email.strip().lower())
    )
    if usuario is None or not usuario.ativo:
        # Confere mesmo assim, para o tempo de resposta nao revelar se o e-mail existe.
        _hasher.hash(senha)
        return None
    confere, novo_hash = conferir(senha, usuario.senha_hash)
    if not confere:
        return None
    if novo_hash:
        usuario.senha_hash = novo_hash
    return usuario


def abrir_sessao(resposta, usuario: Usuario) -> None:
    resposta.set_cookie(
        COOKIE,
        _serializador().dumps({"id": usuario.id}),
        max_age=VALIDADE,
        httponly=True,
        samesite="lax",
        secure=not config.desenvolvimento,
    )


def fechar_sessao(resposta) -> None:
    resposta.delete_cookie(COOKIE)


def usuario_da_requisicao(request: Request, s: Session) -> Usuario | None:
    bruto = request.cookies.get(COOKIE)
    if not bruto:
        return None
    try:
        dados = _serializador().loads(bruto, max_age=VALIDADE)
    except (BadSignature, SignatureExpired):
        return None
    usuario = s.get(Usuario, dados.get("id"))
    return usuario if usuario and usuario.ativo else None


# ── dependencias ────────────────────────────────────────────────────────────────

class NaoAutenticado(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_401_UNAUTHORIZED, "Faça login para continuar.")


class SemPermissao(HTTPException):
    def __init__(self, detalhe: str = "Você não tem acesso a esta área.") -> None:
        super().__init__(status.HTTP_403_FORBIDDEN, detalhe)


def exigir_login(request: Request, s: Session = Depends(obter_sessao)) -> Usuario:
    usuario = usuario_da_requisicao(request, s)
    if usuario is None:
        raise NaoAutenticado()
    return usuario


def exigir_admin(usuario: Usuario = Depends(exigir_login)) -> Usuario:
    if usuario.papel is not Papel.ADMIN:
        raise SemPermissao("Esta área é exclusiva da coordenação.")
    return usuario


@dataclass
class Escopo:
    """O que o usuario pode ver. O professor fica restrito as materias dele."""

    usuario: Usuario

    @property
    def admin(self) -> bool:
        return self.usuario.papel is Papel.ADMIN

    def materias(self) -> list[Materia]:
        if self.admin:
            return list(Materia)
        return [m for m in Materia if m.value in self.usuario.materias_lista]

    def pode_ver(self, materia: Materia | str) -> bool:
        return self.usuario.pode_ver(materia)

    def exigir(self, materia: Materia | str) -> None:
        if not self.pode_ver(materia):
            valor = materia.value if isinstance(materia, Materia) else materia
            raise SemPermissao(f"Você não tem acesso a {valor}.")


def escopo(usuario: Usuario = Depends(exigir_login)) -> Escopo:
    return Escopo(usuario)


# ── contas ──────────────────────────────────────────────────────────────────────

def criar_usuario(
    s: Session,
    *,
    email: str,
    nome: str,
    papel: Papel = Papel.PROFESSOR,
    materias: list[str] | None = None,
    senha: str | None = None,
) -> tuple[Usuario, str]:
    """Cria a conta e devolve (usuario, senha inicial) para a coordenacao repassar."""
    email = email.strip().lower()
    if s.scalar(select(Usuario).where(func.lower(Usuario.email) == email)):
        raise ValueError(f"Já existe uma conta com o e-mail {email}.")

    inicial = senha or gerar_senha()
    usuario = Usuario(
        email=email,
        nome=nome.strip(),
        senha_hash=cifrar(inicial),
        papel=papel,
        materias=",".join(materias or []),
    )
    s.add(usuario)
    s.flush()
    return usuario, inicial


def trocar_senha(usuario: Usuario, senha_atual: str, nova: str) -> None:
    confere, _ = conferir(senha_atual, usuario.senha_hash)
    if not confere:
        raise ValueError("A senha atual não confere.")
    if len(nova) < 8:
        raise ValueError("A nova senha precisa ter ao menos 8 caracteres.")
    usuario.senha_hash = cifrar(nova)
