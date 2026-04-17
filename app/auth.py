"""Autenticação: hash de senhas, sessões, verificação de permissões."""
from __future__ import annotations

import hashlib
import json
import secrets
from typing import Optional

from fastapi import Request
from fastapi.responses import RedirectResponse

ABAS_DISPONIVEIS = ["dia", "grade", "individual", "cadastros", "usuarios"]


# ---------- Senhas ----------

def hash_senha(senha: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt.encode(), 260_000)
    return f"{salt}:{dk.hex()}"


def verificar_senha(senha: str, hash_armazenado: str) -> bool:
    try:
        salt, dk_hex = hash_armazenado.split(":", 1)
        dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt.encode(), 260_000)
        return secrets.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


# ---------- Sessão ----------

def get_usuario_sessao(request: Request) -> Optional[dict]:
    return request.session.get("usuario")


def _redirect_login(request: Request) -> RedirectResponse:
    return RedirectResponse(url=f"/login?next={request.url.path}", status_code=302)


def exigir_login(request: Request) -> Optional[RedirectResponse]:
    if not request.session.get("usuario"):
        return _redirect_login(request)
    return None


def verificar_permissao(request: Request, aba: str) -> Optional[RedirectResponse]:
    usuario = request.session.get("usuario")
    if not usuario:
        return _redirect_login(request)
    if usuario.get("is_admin"):
        return None
    abas = usuario.get("abas_permitidas", [])
    if aba not in abas:
        return RedirectResponse(url="/sem-acesso", status_code=302)
    return None


# ---------- Queries de usuários ----------

from .database import db_cursor  # noqa: E402 (import tardio pra evitar circular)


def listar_usuarios() -> list[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT id, username, nome, is_admin, abas_permitidas, ativo FROM usuarios ORDER BY id")
        rows = cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["abas_list"] = json.loads(d["abas_permitidas"])
        except Exception:
            d["abas_list"] = []
        result.append(d)
    return result


def obter_usuario_por_username(username: str) -> Optional[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM usuarios WHERE username = ? AND ativo = 1", (username,))
        row = cur.fetchone()
    return dict(row) if row else None


def criar_usuario(username: str, nome: str, senha: str, is_admin: bool, abas: list[str]) -> int:
    h = hash_senha(senha)
    abas_json = json.dumps(abas)
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO usuarios (username, nome, senha_hash, is_admin, abas_permitidas) VALUES (?,?,?,?,?)",
            (username.strip().lower(), nome.strip(), h, 1 if is_admin else 0, abas_json),
        )
        return cur.lastrowid


def atualizar_usuario(
    uid: int,
    nome: Optional[str] = None,
    senha: Optional[str] = None,
    is_admin: Optional[bool] = None,
    abas: Optional[list[str]] = None,
    ativo: Optional[bool] = None,
) -> None:
    campos, valores = [], []
    if nome is not None:
        campos.append("nome = ?"); valores.append(nome.strip())
    if senha:
        campos.append("senha_hash = ?"); valores.append(hash_senha(senha))
    if is_admin is not None:
        campos.append("is_admin = ?"); valores.append(1 if is_admin else 0)
    if abas is not None:
        campos.append("abas_permitidas = ?"); valores.append(json.dumps(abas))
    if ativo is not None:
        campos.append("ativo = ?"); valores.append(1 if ativo else 0)
    if not campos:
        return
    valores.append(uid)
    with db_cursor() as cur:
        cur.execute(f"UPDATE usuarios SET {', '.join(campos)} WHERE id = ?", valores)


def remover_usuario(uid: int) -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM usuarios WHERE id = ?", (uid,))
