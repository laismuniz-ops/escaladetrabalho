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
    nome: str, cargo: str, setor: str, tipo: str, ordem: int = 0, genero: str = "M"
) -> int:
    if tipo not in TIPOS_VALIDOS:
        raise ValueError(f"tipo inválido: {tipo}")
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO funcionarios (nome, cargo, setor, tipo, ordem, genero)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (nome, cargo, setor.upper(), tipo, ordem, genero.upper()),
        )
        return cur.lastrowid


def atualizar_funcionario(
    func_id: int,
    nome: Optional[str] = None,
    cargo: Optional[str] = None,
    setor: Optional[str] = None,
    tipo: Optional[str] = None,
    ativo: Optional[bool] = None,
    genero: Optional[str] = None,
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
    if genero is not None:
        campos.append("genero = ?")
        valores.append(genero.upper())
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
        "COZINHA":        {"MANHA": {i: 0 for i in range(7)}, "TARDE": {i: 0 for i in range(7)}},
        "ATENDIMENTO":    {"MANHA": {i: 0 for i in range(7)}, "TARDE": {i: 0 for i in range(7)}},
        "ADMINISTRATIVO": {"MANHA": {i: 0 for i in range(7)}, "TARDE": {i: 0 for i in range(7)}},
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


# ---------- Entregadores ----------

STATUS_ENTREGADOR = {"ESCALADO", "CONFIRMADO"}

def listar_entregadores(ativos_apenas: bool = True) -> list[dict]:
    sql = "SELECT * FROM entregadores WHERE 1=1"
    if ativos_apenas:
        sql += " AND ativo = 1"
    sql += " ORDER BY ordem, id"
    with db_cursor() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]

def criar_entregador(nome: str, obs: str = "", cor: str = "", telefone: str = "", ordem: int = 0) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO entregadores (nome, obs, cor, telefone, ordem) VALUES (?, ?, ?, ?, ?)",
            (nome.strip(), obs.strip(), cor.strip(), telefone.strip(), ordem),
        )
        return cur.lastrowid

def atualizar_entregador(eid: int, nome: str = None, ativo: bool = None,
                          obs: str = None, cor: str = None, telefone: str = None) -> None:
    campos, valores = [], []
    if nome is not None:
        campos.append("nome = ?"); valores.append(nome.strip())
    if ativo is not None:
        campos.append("ativo = ?"); valores.append(1 if ativo else 0)
    if obs is not None:
        campos.append("obs = ?"); valores.append(obs.strip())
    if cor is not None:
        campos.append("cor = ?"); valores.append(cor.strip())
    if telefone is not None:
        campos.append("telefone = ?"); valores.append(telefone.strip())
    if not campos:
        return
    valores.append(eid)
    with db_cursor() as cur:
        cur.execute(f"UPDATE entregadores SET {', '.join(campos)} WHERE id = ?", valores)

def set_obs_entregador(eid: int, texto: str) -> None:
    with db_cursor() as cur:
        cur.execute("UPDATE entregadores SET obs = ? WHERE id = ?", (texto.strip(), eid))

def set_telefone_entregador(eid: int, telefone: str) -> None:
    with db_cursor() as cur:
        cur.execute("UPDATE entregadores SET telefone = ? WHERE id = ?", (telefone.strip(), eid))

def set_cor_entregador(eid: int, cor: str) -> None:
    """cor: 'RAPIDO', 'NORMAL' ou '' para limpar."""
    validos = {"RAPIDO", "NORMAL", ""}
    if cor not in validos:
        raise ValueError(f"Cor inválida: {cor}")
    with db_cursor() as cur:
        cur.execute("UPDATE entregadores SET cor = ? WHERE id = ?", (cor, eid))

def remover_entregador(eid: int) -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM entregadores WHERE id = ?", (eid,))

def toggle_ativo_entregador(eid: int) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT ativo FROM entregadores WHERE id = ?", (eid,))
        row = cur.fetchone()
        if not row:
            raise ValueError("Entregador não encontrado")
        novo = 0 if row["ativo"] else 1
        cur.execute("UPDATE entregadores SET ativo = ? WHERE id = ?", (novo, eid))
        return bool(novo)

def mover_entregador(eid: int, direcao: str) -> None:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM entregadores ORDER BY ordem, id")
        ids = [r["id"] for r in cur.fetchall()]
        try:
            pos = ids.index(eid)
        except ValueError:
            return
        if direcao == "up" and pos > 0:
            ids[pos], ids[pos-1] = ids[pos-1], ids[pos]
        elif direcao == "down" and pos < len(ids) - 1:
            ids[pos], ids[pos+1] = ids[pos+1], ids[pos]
        else:
            return
        for i, fid in enumerate(ids):
            cur.execute("UPDATE entregadores SET ordem = ? WHERE id = ?", (i * 10, fid))

def set_status_entregador(eid: int, data_iso: str, status: str = None) -> None:
    with db_cursor() as cur:
        if not status:
            cur.execute("DELETE FROM escala_entregadores WHERE entregador_id = ? AND data = ?", (eid, data_iso))
            return
        if status not in STATUS_ENTREGADOR:
            raise ValueError(f"Status inválido: {status}")
        cur.execute(
            """INSERT INTO escala_entregadores (entregador_id, data, status) VALUES (?, ?, ?)
               ON CONFLICT(entregador_id, data) DO UPDATE SET status = excluded.status""",
            (eid, data_iso, status)
        )

def escala_entregadores_do_dia(data_iso: str) -> list[dict]:
    """Retorna entregadores escalados ou confirmados no dia."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT e.id, e.nome, e.cor, e.obs, ee.status
            FROM escala_entregadores ee
            JOIN entregadores e ON e.id = ee.entregador_id
            WHERE ee.data = ? AND ee.status IN ('ESCALADO', 'CONFIRMADO')
            ORDER BY e.ordem, e.nome
        """, (data_iso,))
        return [dict(r) for r in cur.fetchall()]


def escala_entregadores_mensal(ano: int, mes: int) -> dict[int, dict[str, str]]:
    primeiro = f"{ano:04d}-{mes:02d}-01"
    proximo = f"{ano+1:04d}-01-01" if mes == 12 else f"{ano:04d}-{mes+1:02d}-01"
    resultado = {}
    with db_cursor() as cur:
        cur.execute(
            "SELECT entregador_id, data, status FROM escala_entregadores WHERE data >= ? AND data < ?",
            (primeiro, proximo)
        )
        for row in cur.fetchall():
            resultado.setdefault(row["entregador_id"], {})[row["data"]] = row["status"]
    return resultado


# ---------- Mínimo de entregadores por dia da semana ----------

def get_min_entregadores_dia() -> list:
    """Retorna lista de 7 ints [min_seg, min_ter, ..., min_dom] (índice = weekday())."""
    with db_cursor() as cur:
        cur.execute("SELECT dia_semana, minimo FROM min_entregadores_dia")
        rows = {r["dia_semana"]: r["minimo"] for r in cur.fetchall()}
    return [rows.get(i, 0) for i in range(7)]


def set_min_entregadores_dia(dia_semana: int, minimo: int) -> None:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO min_entregadores_dia (dia_semana, minimo) VALUES (?, ?) "
            "ON CONFLICT(dia_semana) DO UPDATE SET minimo = excluded.minimo",
            (dia_semana, max(0, minimo)),
        )


# ---------- Feriados ----------

def listar_feriados_ano(ano: int) -> dict:
    """Retorna {data_iso: nome} dos feriados do ano."""
    with db_cursor() as cur:
        cur.execute("SELECT data, nome FROM feriados WHERE data LIKE ?", (f"{ano}-%",))
        return {row["data"]: row["nome"] for row in cur.fetchall()}

def set_feriado(data_iso: str, nome: str) -> None:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO feriados (data, nome) VALUES (?,?) ON CONFLICT(data) DO UPDATE SET nome=excluded.nome",
            (data_iso, nome.strip()),
        )

def remover_feriado(data_iso: str) -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM feriados WHERE data = ?", (data_iso,))


# ---------- Geração automática de escala de entregadores ----------

import calendar as _cal
import re as _re

# Padrões para detectar dias disponíveis na obs do entregador
# Formato sugerido na obs: "dias: seg ter qui"  ou  "só segunda e sexta"
_DIAS_OBS_PADROES = [
    (r"\bsegunda(?:-feira)?\b", 0),
    (r"\bter[cç]a(?:-feira)?\b", 1),
    (r"\bquarta(?:-feira)?\b", 2),
    (r"\bquinta(?:-feira)?\b", 3),
    (r"\bsexta(?:-feira)?\b", 4),
    (r"\bs[áa]bado\b", 5),
    (r"\bdomingo\b", 6),
    # Abreviações (usadas em listas, ex: "dias: seg ter qui")
    (r"\bseg\b", 0),
    (r"\bter\b", 1),
    (r"\bqua\b", 2),
    (r"\bqui\b", 3),
    (r"\bsex\b", 4),
    (r"\bs[áa]b\b", 5),
    (r"\bdom\b", 6),
]


def _dias_disponiveis_obs(obs: str) -> "dict | None":
    """
    Lê restrições de disponibilidade na obs do entregador.
    Retorna dict {"dias_semana": set|None, "paridade": "par"|"impar"|None}
    ou None se não houver nenhuma restrição.

    Exemplos:
      'dias: seg ter qui'  → dias_semana={0,1,3}, paridade=None
      'só segunda e sexta' → dias_semana={0,4},   paridade=None
      'pares'              → dias_semana=None,     paridade="par"
      'ímpares'            → dias_semana=None,     paridade="impar"
      'seg pares'          → dias_semana={0},      paridade="par"
    """
    if not obs:
        return None
    s = obs.lower()

    # Paridade do dia do mês
    paridade = None
    if _re.search(r'\b[ií]mpares?\b', s):
        paridade = "impar"
    elif _re.search(r'\bpares?\b', s):
        paridade = "par"

    # Dias da semana
    dias_semana: set = set()
    for padrao, dow in _DIAS_OBS_PADROES:
        if _re.search(padrao, s):
            dias_semana.add(dow)
    dias_semana_rest = dias_semana if dias_semana else None

    if paridade is None and dias_semana_rest is None:
        return None
    return {"dias_semana": dias_semana_rest, "paridade": paridade}

# ── Snapshot em memória para undo da última geração (por mês)
_undo_escala: dict = {}

def _salvar_snapshot_geracao(ano: int, mes: int) -> None:
    """Salva estado atual da escala do mês para possível undo."""
    primeiro = f"{ano:04d}-{mes:02d}-01"
    proximo = f"{ano+1:04d}-01-01" if mes == 12 else f"{ano:04d}-{mes+1:02d}-01"
    with db_cursor() as cur:
        cur.execute(
            "SELECT entregador_id, data, status FROM escala_entregadores WHERE data >= ? AND data < ?",
            (primeiro, proximo),
        )
        rows = [dict(r) for r in cur.fetchall()]
    _undo_escala[f"{ano:04d}-{mes:02d}"] = rows


def restaurar_snapshot_geracao(ano: int, mes: int) -> int:
    """Restaura escala do mês para o estado antes da última geração. Retorna nº de linhas."""
    key = f"{ano:04d}-{mes:02d}"
    if key not in _undo_escala:
        raise ValueError("Nenhuma geração recente para desfazer neste mês.")
    snapshot = _undo_escala.pop(key)
    primeiro = f"{ano:04d}-{mes:02d}-01"
    proximo = f"{ano+1:04d}-01-01" if mes == 12 else f"{ano:04d}-{mes+1:02d}-01"
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM escala_entregadores WHERE data >= ? AND data < ?",
            (primeiro, proximo),
        )
        for row in snapshot:
            cur.execute(
                "INSERT INTO escala_entregadores (entregador_id, data, status) VALUES (?, ?, ?)",
                (row["entregador_id"], row["data"], row["status"]),
            )
    return len(snapshot)


def gerar_escala_auto(
    ano: int,
    mes: int,
    total_por_dia_semana: list,       # 7 ints, índice = weekday() 0=Seg…6=Dom
    min_rapido_semana: list,           # 7 ints, mesmo índice
    min_normal_semana: list,           # 7 ints, mesmo índice
    dias_especificos: list = None,
    sobrescrever: bool = False,
    max_dias_semana: int = 2,          # máx. de dias por semana Dom–Sáb por entregador
) -> dict:
    """
    Gera escala automática.
    - total_por_dia_semana: 7 valores, um por dia da semana (0=Seg … 6=Dom)
    - Distribui de forma equilibrada (quem trabalhou menos vai primeiro)
    - Garante mínimos de Rápidos e Normais por dia
    - Respeita limite de max_dias_semana dias por semana Dom–Sáb por entregador
      (inclui dias do mês anterior que pertencem à 1ª semana parcial)
    - dias_especificos: lista de ISO strings; None = todos os dias do mês
    """
    from datetime import date as _date, timedelta as _td

    drivers = listar_entregadores(ativos_apenas=True)
    if not drivers:
        return {"erro": "Nenhum entregador ativo.", "dias_gerados": 0, "contagem": [], "avisos": []}

    # Salva snapshot antes de qualquer modificação (permite undo)
    _salvar_snapshot_geracao(ano, mes)

    rapidos = [d for d in drivers if d["cor"] == "RAPIDO"]
    normais  = [d for d in drivers if d["cor"] == "NORMAL"]

    avisos = []
    if max(min_rapido_semana) > len(rapidos):
        avisos.append(f"Apenas {len(rapidos)} Rápido(s) disponível(is).")
    if max(min_normal_semana) > len(normais):
        avisos.append(f"Apenas {len(normais)} Normal(is) disponível(is).")

    def _semana_chave(d: _date) -> str:
        """Retorna o ISO da data do domingo que inicia a semana Dom–Sáb do dia d."""
        return (d - _td(days=(d.weekday() + 1) % 7)).isoformat()

    # Dias a trabalhar
    if dias_especificos:
        dias_trabalho = sorted([_date.fromisoformat(d) for d in dias_especificos])
    else:
        num_dias = _cal.monthrange(ano, mes)[1]
        dias_trabalho = [_date(ano, mes, d) for d in range(1, num_dias + 1)]

    # Escala já existente no mês
    existente = escala_entregadores_mensal(ano, mes)
    dias_existentes: set = set()
    if not sobrescrever:
        for turnos in existente.values():
            dias_existentes.update(turnos.keys())

    # ── Dias disponíveis por entregador (lidos da obs)
    dias_disponiveis: dict = {}
    for d in drivers:
        restricao = _dias_disponiveis_obs(d.get("obs") or "")
        dias_disponiveis[d["id"]] = restricao  # None = sem restrição

    contagem = {d["id"]: 0 for d in drivers}
    semanas: dict = {d["id"]: {} for d in drivers}

    # ── Pré-popula semanas com escala já existente no mês (respeita limite ao completar)
    if not sobrescrever:
        for eid, dias_map in existente.items():
            if eid not in semanas:
                continue
            for iso_dia, status in dias_map.items():
                if status in ("ESCALADO", "CONFIRMADO"):
                    ck = _semana_chave(_date.fromisoformat(iso_dia))
                    semanas[eid][ck] = semanas[eid].get(ck, 0) + 1

    # ── Pré-popula semanas com dias do mês anterior que pertencem à 1ª semana parcial
    #    (ex.: se o mês começa numa Quarta, os dias Domingo–Terça do mês anterior
    #     pertencem à mesma semana Dom–Sáb e devem contar para o limite de 2x)
    primeiro_dia_mes = _date(ano, mes, 1)
    inicio_semana_1 = _date.fromisoformat(_semana_chave(primeiro_dia_mes))
    if inicio_semana_1 < primeiro_dia_mes:
        data_ini_prev = inicio_semana_1.isoformat()
        data_fim_prev = (primeiro_dia_mes - _td(days=1)).isoformat()
        with db_cursor() as cur:
            cur.execute("""
                SELECT entregador_id FROM escala_entregadores
                WHERE data >= ? AND data <= ? AND status IN ('ESCALADO', 'CONFIRMADO')
            """, (data_ini_prev, data_fim_prev))
            for row in cur.fetchall():
                eid = row["entregador_id"]
                if eid in semanas:
                    ck = inicio_semana_1.isoformat()
                    semanas[eid][ck] = semanas[eid].get(ck, 0) + 1

    dias_gerados = 0
    dias_processados: list = []
    escalados_por_dia: dict = {}
    dias_pulados = 0        # dias que já tinham escala e foram ignorados (sobrescrever=False)
    dias_vazios = 0         # dias gerados mas com 0 entregadores disponíveis

    for dia in dias_trabalho:
        iso = dia.isoformat()
        if not sobrescrever and iso in dias_existentes:
            dias_pulados += 1
            continue

        cal_week = _semana_chave(dia)
        dow = dia.weekday()
        _min_r_hoje = min(min_rapido_semana[dow], len(rapidos))
        _min_n_hoje = min(min_normal_semana[dow], len(normais))

        def elegivel(d, _cw=cal_week, _dow=dow, _dnum=dia.day):
            # Limite semanal (Dom–Sáb)
            if semanas[d["id"]].get(_cw, 0) >= max_dias_semana:
                return False
            # Restrições da obs
            restricao = dias_disponiveis.get(d["id"])
            if restricao is not None:
                if restricao["dias_semana"] is not None and _dow not in restricao["dias_semana"]:
                    return False
                if restricao["paridade"] == "par" and _dnum % 2 != 0:
                    return False
                if restricao["paridade"] == "impar" and _dnum % 2 == 0:
                    return False
            return True

        elig_rapidos = [d for d in rapidos if elegivel(d)]
        elig_normais  = [d for d in normais  if elegivel(d)]
        elig_todos    = [d for d in drivers  if elegivel(d)]

        selecionados: set = set()

        # 1. Rápidos com menos dias primeiro
        r_sorted = sorted(elig_rapidos, key=lambda d: (contagem[d["id"]], d["ordem"]))
        for d in r_sorted[:_min_r_hoje]:
            selecionados.add(d["id"])

        # 2. Normais com menos dias primeiro
        n_sorted = sorted(elig_normais, key=lambda d: (contagem[d["id"]], d["ordem"]))
        for d in n_sorted[:_min_n_hoje]:
            selecionados.add(d["id"])

        # 3. Preenche restante com qualquer elegível
        total_hoje = total_por_dia_semana[dia.weekday()]
        restante = max(0, total_hoje - len(selecionados))
        if restante:
            pool = sorted(
                [d for d in elig_todos if d["id"] not in selecionados],
                key=lambda d: (contagem[d["id"]], d["ordem"]),
            )
            for d in pool[:restante]:
                selecionados.add(d["id"])

        if not selecionados:
            dias_vazios += 1

        # Salva
        for d in drivers:
            if d["id"] in selecionados:
                set_status_entregador(d["id"], iso, "ESCALADO")
                contagem[d["id"]] += 1
                semanas[d["id"]][cal_week] = semanas[d["id"]].get(cal_week, 0) + 1

        dias_gerados += 1
        dias_processados.append(iso)
        for d in drivers:
            if d["id"] in selecionados:
                escalados_por_dia.setdefault(iso, []).append(d["id"])

    if dias_vazios > 0:
        avisos.append(
            f"{dias_vazios} dia(s) gerado(s) sem nenhum entregador disponível "
            "(limite semanal atingido ou restrição de dias na obs)."
        )

    return {
        "dias_gerados": dias_gerados,
        "dias_pulados": dias_pulados,
        "avisos": avisos,
        "dias_processados": dias_processados,
        "escalados_por_dia": escalados_por_dia,
        "contagem": [
            {
                "nome": d["nome"],
                "cor": d["cor"],
                "obs": d.get("obs") or "",
                "dias": contagem[d["id"]],
            }
            for d in sorted(drivers, key=lambda d: -contagem[d["id"]])
        ],
    }


def limpar_escala_entregadores(ano: int, mes: int, dias_especificos: list = None) -> int:
    """Remove entradas de escala_entregadores do mês (ou dias específicos).
    Retorna o número de registros removidos."""
    if dias_especificos:
        placeholders = ",".join("?" * len(dias_especificos))
        with db_cursor() as cur:
            cur.execute(
                f"DELETE FROM escala_entregadores WHERE data IN ({placeholders})",
                dias_especificos,
            )
            return cur.rowcount
    else:
        primeiro = f"{ano:04d}-{mes:02d}-01"
        proximo = f"{ano+1:04d}-01-01" if mes == 12 else f"{ano:04d}-{mes+1:02d}-01"
        with db_cursor() as cur:
            cur.execute(
                "DELETE FROM escala_entregadores WHERE data >= ? AND data < ?",
                (primeiro, proximo),
            )
            return cur.rowcount


# ═══════════════════════════════════════════════════════════════════════════════
# Geração automática de escala de colaboradores CONTRATADOS
# ═══════════════════════════════════════════════════════════════════════════════

_undo_colab: dict = {}


def _salvar_snapshot_colab(ano: int, mes: int) -> None:
    """Snapshot do mês para undo da geração de colaboradores."""
    primeiro = f"{ano:04d}-{mes:02d}-01"
    proximo  = f"{ano+1:04d}-01-01" if mes == 12 else f"{ano:04d}-{mes+1:02d}-01"
    with db_cursor() as cur:
        cur.execute(
            "SELECT funcionario_id, data, turno FROM escala WHERE data >= ? AND data < ?",
            (primeiro, proximo),
        )
        _undo_colab[f"{ano:04d}-{mes:02d}"] = [dict(r) for r in cur.fetchall()]


def restaurar_snapshot_colab(ano: int, mes: int) -> int:
    """Desfaz a última geração automática de colaboradores."""
    key = f"{ano:04d}-{mes:02d}"
    if key not in _undo_colab:
        raise ValueError("Nenhuma geração recente para desfazer neste mês.")
    snapshot = _undo_colab.pop(key)
    primeiro = f"{ano:04d}-{mes:02d}-01"
    proximo  = f"{ano+1:04d}-01-01" if mes == 12 else f"{ano:04d}-{mes+1:02d}-01"
    with db_cursor() as cur:
        cur.execute("DELETE FROM escala WHERE data >= ? AND data < ?", (primeiro, proximo))
        for row in snapshot:
            cur.execute(
                "INSERT INTO escala (funcionario_id, data, turno) VALUES (?, ?, ?)",
                (row["funcionario_id"], row["data"], row["turno"]),
            )
    return len(snapshot)


def gerar_escala_colab_auto(
    ano: int,
    mes: int,
    sobrescrever: bool = False,
    preencher_trabalho: bool = True,
    dias_especificos: list = None,
    setores: list = None,
) -> dict:
    """
    Gera escala automática de FOLGAS para colaboradores CONTRATADOS.

    Regras:
    • 1 folga por semana (Dom, Ter, Qua ou Qui — nunca Seg, Sex, Sáb)
    • Mulheres: 2 folgas no domingo por mês; Homens: 1
    • Domingos de folga são atribuídos em semanas consecutivas (evita streak > 6)
    • Folgas mid-week são rotacionadas entre Ter/Qua/Qui por funcionário
    • Respeita mínimos de escala por setor/turno/dia da semana
    • Máximo 6 dias consecutivos de trabalho; folga extra inserida se necessário
    • preencher_trabalho=True → dias sem folga recebem MANHA+TARDE
    """
    import calendar as _cal
    from datetime import date as _date, timedelta as _td
    from collections import defaultdict

    MIDWEEK_DOWS = [1, 2, 3]  # Ter=1, Qua=2, Qui=3

    todos_funcionarios = listar_funcionarios(tipo="CONTRATADO", ativos_apenas=True)
    if not todos_funcionarios:
        return {"erro": "Nenhum colaborador contratado ativo.", "gerados": 0, "avisos": []}

    minimos = get_minimos()

    # Total de CONTRATADOS por setor — usa TODOS (base correta para mínimos)
    setor_total: dict[str, int] = defaultdict(int)
    for f in todos_funcionarios:
        setor_total[f["setor"]] += 1

    # Filtra pelos setores selecionados (somente para geração, não para contagem de mínimos)
    if setores:
        funcionarios = [f for f in todos_funcionarios if f["setor"] in setores]
    else:
        funcionarios = todos_funcionarios

    if not funcionarios:
        setores_str = ", ".join(setores) if setores else "—"
        return {"erro": f"Nenhum colaborador nos setores selecionados ({setores_str}).", "gerados": 0, "avisos": []}

    num_dias = _cal.monthrange(ano, mes)[1]
    datas_mes = [_date(ano, mes, d) for d in range(1, num_dias + 1)]
    datas_alvo = (
        sorted([_date.fromisoformat(d) for d in dias_especificos])
        if dias_especificos else datas_mes
    )

    # ── Semanas do mês (Mon-Sun) ──────────────────────────────────────────────
    semanas_dict: dict = {}
    for d in datas_mes:
        seg = d - _td(days=d.weekday())
        semanas_dict.setdefault(seg, []).append(d)
    semanas = sorted(semanas_dict.items())  # [(segunda, [datas...]), ...]

    dom_por_semana: dict = {
        seg: next((d for d in dates if d.weekday() == 6), None)
        for seg, dates in semanas
    }
    semanas_com_dom = [seg for seg, dom in dom_por_semana.items() if dom is not None]

    # ── Snapshot para undo ────────────────────────────────────────────────────
    _salvar_snapshot_colab(ano, mes)

    # ── Contexto do mês anterior (semanas entre meses) ────────────────────────
    mes_ant = mes - 1 if mes > 1 else 12
    ano_ant = ano if mes > 1 else ano - 1
    escala_mes_ant = escala_mensal(ano_ant, mes_ant, tipo="CONTRATADO")

    # Primeira semana do mês: pode começar antes do dia 1
    primeiro_dia_mes = datas_mes[0]
    primeira_semana_seg = semanas[0][0]  # segunda-feira da 1ª semana

    # Para cada funcionário: já tem folga na primeira semana (vinda do mês anterior)?
    folga_na_primeira_sem: dict[int, bool] = {}
    for f in funcionarios:
        fid_tmp = f["id"]
        folga_na_primeira_sem[fid_tmp] = False
        if primeira_semana_seg < primeiro_dia_mes:
            d_tmp = primeira_semana_seg
            esc_ant_f = escala_mes_ant.get(fid_tmp, {})
            while d_tmp < primeiro_dia_mes:
                if esc_ant_f.get(d_tmp.isoformat(), "") in ("FOLGA", "FERIAS", "AFASTAMENTO"):
                    folga_na_primeira_sem[fid_tmp] = True
                    break
                d_tmp += _td(days=1)

    # Streak inicial: dias consecutivos de trabalho no final do mês anterior
    streak_inicial: dict[int, int] = {}
    for f in funcionarios:
        fid_tmp = f["id"]
        s_tmp = 0
        d_tmp = primeiro_dia_mes - _td(days=1)
        esc_ant_f = escala_mes_ant.get(fid_tmp, {})
        while s_tmp < 6:
            turno_tmp = esc_ant_f.get(d_tmp.isoformat(), "")
            if turno_tmp in ("FOLGA", "FERIAS", "AFASTAMENTO") or not turno_tmp:
                break
            s_tmp += 1
            d_tmp -= _td(days=1)
        streak_inicial[fid_tmp] = s_tmp

    # ── Escala existente (para respeitar sobrescrever=False) ──────────────────
    escala_exist = {} if sobrescrever else escala_mensal(ano, mes, tipo="CONTRATADO")

    avisos: list[str] = []
    # Folgas já atribuídas por (data, setor) — para a checagem de mínimos
    folgas_no_dia: dict = defaultdict(int)

    # Índices de rotação por gênero
    idx_por_genero: dict[str, int] = {"M": 0, "F": 0}

    for idx_global, f in enumerate(funcionarios):
        fid    = f["id"]
        genero = f.get("genero", "M")
        setor  = f["setor"]
        n_dom  = 2 if genero == "F" else 1

        idx_g = idx_por_genero[genero]
        idx_por_genero[genero] += 1

        # ── Semanas com folga no domingo ──────────────────────────────────────
        folgas_dom_semanas: set = set()
        n_disp = len(semanas_com_dom)
        if n_disp > 0:
            if n_dom >= 2 and n_disp >= 2:
                # Dois domingos consecutivos, rodando entre funcionárias
                par = idx_g % (n_disp - 1)
                folgas_dom_semanas.add(semanas_com_dom[par])
                folgas_dom_semanas.add(semanas_com_dom[par + 1])
            else:
                folgas_dom_semanas.add(semanas_com_dom[idx_g % n_disp])

        # Dia mid-week preferido (rotado por funcionário)
        midweek_dow = MIDWEEK_DOWS[idx_global % 3]

        # ── Plano de folgas semana a semana ───────────────────────────────────
        folgas_planejadas: list[_date] = []

        for seg, dates_sem in semanas:
            # Se a primeira semana já contém folga do mês anterior, pula
            if seg == primeira_semana_seg and folga_na_primeira_sem.get(fid, False):
                continue
            if seg in folgas_dom_semanas:
                dom = dom_por_semana.get(seg)
                candidatos = ([dom] if dom else []) + [
                    d for d in dates_sem if d.weekday() in MIDWEEK_DOWS
                ]
            else:
                pref   = [d for d in dates_sem if d.weekday() == midweek_dow]
                outras = [d for d in dates_sem if d.weekday() in MIDWEEK_DOWS
                          and d.weekday() != midweek_dow]
                candidatos = pref + outras

            folga_ok = None
            for d in candidatos:
                if d not in datas_alvo:
                    continue
                # Checa se folga respeita mínimos do setor
                dow    = d.weekday()
                viavel = True
                if setor in minimos:
                    for turno_key in ("MANHA", "TARDE"):
                        min_val = minimos[setor][turno_key].get(dow, 0)
                        if min_val > 0:
                            disponiveis = setor_total[setor] - folgas_no_dia[(d, setor)]
                            if disponiveis - 1 < min_val:
                                viavel = False
                                break
                if viavel:
                    folga_ok = d
                    folgas_no_dia[(d, setor)] += 1
                    break

            if folga_ok is None and candidatos:
                # Força melhor candidato disponível com aviso
                for d in candidatos:
                    if d in datas_alvo:
                        folga_ok = d
                        folgas_no_dia[(d, setor)] += 1
                        avisos.append(
                            f"{f['nome']}: folga em {d.strftime('%d/%m')} "
                            f"pode deixar {setor.capitalize()} abaixo do mínimo."
                        )
                        break

            if folga_ok:
                folgas_planejadas.append(folga_ok)

        # ── Corrige streaks > 6 dias consecutivos ─────────────────────────────
        folgas_set = set(folgas_planejadas)
        streak = streak_inicial.get(fid, 0)  # inicia com dias trabalhados no fim do mês anterior
        for d in datas_mes:
            if d in folgas_set:
                streak = 0
            else:
                streak += 1
                if streak == 7:
                    inserido = False
                    for k in range(1, 5):
                        c = d - _td(days=k)
                        if (c in datas_alvo
                                and c.weekday() in MIDWEEK_DOWS
                                and c not in folgas_set):
                            folgas_set.add(c)
                            folgas_no_dia[(c, setor)] += 1
                            avisos.append(
                                f"{f['nome']}: folga extra em {c.strftime('%d/%m')} "
                                f"para evitar 7 dias seguidos."
                            )
                            streak = 0
                            inserido = True
                            break
                    if not inserido:
                        folgas_set.add(d)
                        folgas_no_dia[(d, setor)] += 1
                        avisos.append(
                            f"{f['nome']}: folga forçada em {d.strftime('%d/%m')} "
                            f"para evitar 7 dias seguidos."
                        )
                        streak = 0

        # ── Salva no banco ────────────────────────────────────────────────────
        escala_func = escala_exist.get(fid, {})
        for d in datas_alvo:
            iso = d.isoformat()
            if not sobrescrever and iso in escala_func:
                continue
            if d in folgas_set:
                set_turno(fid, iso, "FOLGA")
            elif preencher_trabalho:
                set_turno(fid, iso, "MANHA+TARDE")

    return {
        "gerados": len(funcionarios),
        "dias_alvo": len(datas_alvo),
        "avisos": avisos,
    }
