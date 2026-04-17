"""Camada de acesso a dados (queries sobre SQLite)."""
from __future__ import annotations

from datetime import date
from typing import Optional

from .database import db_cursor

SETORES_ORDEM = ["COZINHA", "ATENDIMENTO", "ADMINISTRATIVO"]
TURNOS_VALIDOS = {"MANHA", "TARDE", "FOLGA", "FERIAS", "AFASTAMENTO"}
TIPOS_VALIDOS = {"CONTRATADO", "EXTRA"}


# ---------- Funcionários ----------

def listar_funcionarios(
    tipo: Optional[str] = None, ativos_apenas: bool = True
) -> list[dict]:
    sql = "SELECT * FROM funcionarios WHERE 1=1"
    params: list = []
    if ativos_apenas:
        sql += " AND ativo = 1"
    if tipo:
        sql += " AND tipo = ?"
        params.append(tipo)
    sql += " ORDER BY ordem, id"
    with db_cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def obter_funcionario(func_id: int) -> Optional[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM funcionarios WHERE id = ?", (func_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def criar_funcionario(
    nome: str, cargo: str, setor: str, tipo: str, ordem: int = 0
) -> int:
    if tipo not in TIPOS_VALIDOS:
        raise ValueError(f"tipo inválido: {tipo}")
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO funcionarios (nome, cargo, setor, tipo, ordem)
               VALUES (?, ?, ?, ?, ?)""",
            (nome, cargo, setor.upper(), tipo, ordem),
        )
        return cur.lastrowid


def atualizar_funcionario(
    func_id: int,
    nome: Optional[str] = None,
    cargo: Optional[str] = None,
    setor: Optional[str] = None,
    tipo: Optional[str] = None,
    ativo: Optional[bool] = None,
) -> None:
    campos = []
    valores: list = []
    if nome is not None:
        campos.append("nome = ?")
        valores.append(nome)
    if cargo is not None:
        campos.append("cargo = ?")
        valores.append(cargo)
    if setor is not None:
        campos.append("setor = ?")
        valores.append(setor.upper())
    if tipo is not None:
        if tipo not in TIPOS_VALIDOS:
            raise ValueError(f"tipo inválido: {tipo}")
        campos.append("tipo = ?")
        valores.append(tipo)
    if ativo is not None:
        campos.append("ativo = ?")
        valores.append(1 if ativo else 0)
    if not campos:
        return
    valores.append(func_id)
    with db_cursor() as cur:
        cur.execute(
            f"UPDATE funcionarios SET {', '.join(campos)} WHERE id = ?",
            valores,
        )


def remover_funcionario(func_id: int) -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM funcionarios WHERE id = ?", (func_id,))


def toggle_ativo(func_id: int) -> bool:
    """Alterna ativo/inativo. Retorna o novo valor."""
    with db_cursor() as cur:
        cur.execute("SELECT ativo FROM funcionarios WHERE id = ?", (func_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError("Funcionário não encontrado")
        novo = 0 if row["ativo"] else 1
        cur.execute("UPDATE funcionarios SET ativo = ? WHERE id = ?", (novo, func_id))
        return bool(novo)


def mover_funcionario(func_id: int, direcao: str) -> None:
    """Move o funcionário para cima ou para baixo dentro do setor (considera tipo)."""
    with db_cursor() as cur:
        cur.execute("SELECT setor, tipo FROM funcionarios WHERE id = ?", (func_id,))
        row = cur.fetchone()
        if not row:
            return
        setor, tipo = row["setor"], row["tipo"]
        cur.execute(
            "SELECT id FROM funcionarios WHERE setor = ? AND tipo = ? ORDER BY ordem, id",
            (setor, tipo),
        )
        ids = [r["id"] for r in cur.fetchall()]
        try:
            pos = ids.index(func_id)
        except ValueError:
            return
        if direcao == "up" and pos > 0:
            ids[pos], ids[pos - 1] = ids[pos - 1], ids[pos]
        elif direcao == "down" and pos < len(ids) - 1:
            ids[pos], ids[pos + 1] = ids[pos + 1], ids[pos]
        else:
            return
        for i, fid in enumerate(ids):
            cur.execute("UPDATE funcionarios SET ordem = ? WHERE id = ?", (i * 10, fid))


# ---------- Escala ----------

def set_turno(funcionario_id: int, data_iso: str, turno: Optional[str]) -> None:
    """Define ou remove o turno de um funcionário numa data.
    turno = None/'' remove a marcação.
    Aceita valores simples ('MANHA') ou compostos ('MANHA+TARDE').
    """
    with db_cursor() as cur:
        if turno is None or turno == "":
            cur.execute(
                "DELETE FROM escala WHERE funcionario_id = ? AND data = ?",
                (funcionario_id, data_iso),
            )
            return
        turno = turno.strip().replace(" ", "+")  # normaliza espaço → + (form url-encoded)
        partes = turno.split("+")
        if not all(p in TURNOS_VALIDOS for p in partes) or len(partes) > 2:
            raise ValueError(f"turno inválido: {turno}")
        cur.execute(
            """INSERT INTO escala (funcionario_id, data, turno)
               VALUES (?, ?, ?)
               ON CONFLICT(funcionario_id, data) DO UPDATE SET turno = excluded.turno""",
            (funcionario_id, data_iso, turno),
        )


def escala_do_dia(data_iso: str) -> list[dict]:
    """Retorna funcionários escalados no dia (MANHA, TARDE ou MANHA+TARDE).
    Inclui contratados e extras."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT f.id, f.nome, f.cargo, f.setor, f.tipo, e.turno
            FROM escala e
            JOIN funcionarios f ON f.id = e.funcionario_id
            WHERE e.data = ?
              AND (e.turno LIKE '%MANHA%' OR e.turno LIKE '%TARDE%')
            ORDER BY f.tipo, f.setor, f.ordem, f.nome
            """,
            (data_iso,),
        )
        return [dict(r) for r in cur.fetchall()]


def escala_mensal(
    ano: int, mes: int, tipo: Optional[str] = None
) -> dict[int, dict[str, str]]:
    """Retorna dict {funcionario_id: {data_iso: turno}} do mês."""
    primeiro = f"{ano:04d}-{mes:02d}-01"
    if mes == 12:
        proximo = f"{ano+1:04d}-01-01"
    else:
        proximo = f"{ano:04d}-{mes+1:02d}-01"
    sql = """
        SELECT e.funcionario_id, e.data, e.turno
        FROM escala e
        JOIN funcionarios f ON f.id = e.funcionario_id
        WHERE e.data >= ? AND e.data < ?
    """
    params: list = [primeiro, proximo]
    if tipo:
        sql += " AND f.tipo = ?"
        params.append(tipo)
    resultado: dict[int, dict[str, str]] = {}
    with db_cursor() as cur:
        cur.execute(sql, params)
        for row in cur.fetchall():
            resultado.setdefault(row["funcionario_id"], {})[row["data"]] = row["turno"]
    return resultado


def escala_individual(funcionario_id: int, ano: int, mes: int) -> dict[str, str]:
    primeiro = f"{ano:04d}-{mes:02d}-01"
    if mes == 12:
        proximo = f"{ano+1:04d}-01-01"
    else:
        proximo = f"{ano:04d}-{mes+1:02d}-01"
    with db_cursor() as cur:
        cur.execute(
            """SELECT data, turno FROM escala
               WHERE funcionario_id = ? AND data >= ? AND data < ?
               ORDER BY data""",
            (funcionario_id, primeiro, proximo),
        )
        return {r["data"]: r["turno"] for r in cur.fetchall()}


def contar_turnos(funcionario_id: int, ano: int, mes: int) -> dict[str, int]:
    turnos = escala_individual(funcionario_id, ano, mes)
    contagem = {"MANHA": 0, "TARDE": 0, "FOLGA": 0, "FERIAS": 0}
    for t in turnos.values():
        if t in contagem:
            contagem[t] += 1
    return contagem


# ---------- Notas (comentários por dia) ----------

def notas_do_mes(funcionario_id: int, ano: int, mes: int) -> dict[str, str]:
    """Retorna dict {data_iso: texto} das notas do funcionário no mês."""
    primeiro = f"{ano:04d}-{mes:02d}-01"
    proximo  = f"{ano+1:04d}-01-01" if mes == 12 else f"{ano:04d}-{mes+1:02d}-01"
    with db_cursor() as cur:
        cur.execute(
            """SELECT data, texto FROM notas
               WHERE funcionario_id = ? AND data >= ? AND data < ?""",
            (funcionario_id, primeiro, proximo),
        )
        return {r["data"]: r["texto"] for r in cur.fetchall()}


# ---------- Mínimos de escala ----------

def get_minimos() -> dict:
    """Retorna {setor: {turno: {dia_semana: minimo}}}
    dia_semana: 0=Segunda, 1=Terça, ..., 6=Domingo."""
    resultado: dict = {
        "COZINHA":     {"MANHA": {i: 0 for i in range(7)}, "TARDE": {i: 0 for i in range(7)}},
        "ATENDIMENTO": {"MANHA": {i: 0 for i in range(7)}, "TARDE": {i: 0 for i in range(7)}},
    }
    with db_cursor() as cur:
        cur.execute("SELECT setor, turno, dia_semana, minimo FROM minimos_escala")
        for row in cur.fetchall():
            s, t, d = row["setor"], row["turno"], row["dia_semana"]
            if s in resultado and t in resultado[s]:
                resultado[s][t][d] = row["minimo"]
    return resultado


def set_minimo(setor: str, turno: str, dia_semana: int, valor: int) -> None:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO minimos_escala (setor, turno, dia_semana, minimo) VALUES (?, ?, ?, ?)
               ON CONFLICT(setor, turno, dia_semana) DO UPDATE SET minimo = excluded.minimo""",
            (setor, turno, dia_semana, max(0, valor)),
        )


def set_nota(funcionario_id: int, data_iso: str, texto: str) -> None:
    """Salva ou apaga uma nota. Texto vazio remove o registro."""
    with db_cursor() as cur:
        if not texto or not texto.strip():
            cur.execute(
                "DELETE FROM notas WHERE funcionario_id = ? AND data = ?",
                (funcionario_id, data_iso),
            )
        else:
            cur.execute(
                """INSERT INTO notas (funcionario_id, data, texto)
                   VALUES (?, ?, ?)
                   ON CONFLICT(funcionario_id, data) DO UPDATE SET texto = excluded.texto""",
                (funcionario_id, data_iso, texto.strip()),
            )
