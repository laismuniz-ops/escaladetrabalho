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

def gerar_escala_auto(
    ano: int,
    mes: int,
    total_por_dia_semana: list,       # 7 ints [dom, seg, ter, qua, qui, sex, sab] → índice = weekday() com dom=6
    min_rapido_semana: list,           # 7 ints, mesmo índice
    min_normal_semana: list,           # 7 ints, mesmo índice
    dias_especificos: list = None,
    sobrescrever: bool = False,
) -> dict:
    """
    Gera escala automática.
    - total_por_dia_semana: 7 valores, um por dia da semana (0=Seg … 6=Dom)
    - Distribui de forma equilibrada (quem trabalhou menos vai primeiro)
    - Garante mínimos de Rápidos e Normais por dia
    - Respeita limite de 2 dias por semana por entregador
    - dias_especificos: lista de ISO strings; None = todos os dias do mês
    """
    from datetime import date as _date

    drivers = listar_entregadores(ativos_apenas=True)
    if not drivers:
        return {"erro": "Nenhum entregador ativo.", "dias_gerados": 0, "contagem": [], "avisos": []}

    rapidos = [d for d in drivers if d["cor"] == "RAPIDO"]
    normais  = [d for d in drivers if d["cor"] == "NORMAL"]

    avisos = []
    if max(min_rapido_semana) > len(rapidos):
        avisos.append(f"Apenas {len(rapidos)} Rápido(s) disponível(is).")
    if max(min_normal_semana) > len(normais):
        avisos.append(f"Apenas {len(normais)} Normal(is) disponível(is).")

    # Dias a trabalhar
    if dias_especificos:
        dias_trabalho = sorted([_date.fromisoformat(d) for d in dias_especificos])
    else:
        num_dias = _cal.monthrange(ano, mes)[1]
        dias_trabalho = [_date(ano, mes, d) for d in range(1, num_dias + 1)]

    # Se não sobrescrever, descobre dias que já têm escala
    dias_existentes: set = set()
    if not sobrescrever:
        existente = escala_entregadores_mensal(ano, mes)
        for turnos in existente.values():
            dias_existentes.update(turnos.keys())

    contagem = {d["id"]: 0 for d in drivers}
    # semanas: {driver_id: {(iso_year, iso_week): count}}
    semanas: dict = {d["id"]: {} for d in drivers}
    dias_gerados = 0

    for dia in dias_trabalho:
        iso = dia.isoformat()
        if not sobrescrever and iso in dias_existentes:
            continue

        # Semana Dom–Sáb: domingo é o 1º dia; chave = data do domingo que inicia a semana
        from datetime import timedelta as _td
        dias_desde_dom = (dia.weekday() + 1) % 7   # dom=0, seg=1, …, sab=6
        semana_inicio = dia - _td(days=dias_desde_dom)
        cal_week = semana_inicio.isoformat()

        dow = dia.weekday()
        _min_r_hoje = min(min_rapido_semana[dow], len(rapidos))
        _min_n_hoje = min(min_normal_semana[dow], len(normais))

        def elegivel(d):
            return semanas[d["id"]].get(cal_week, 0) < 2

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

        # Salva
        for d in drivers:
            if d["id"] in selecionados:
                set_status_entregador(d["id"], iso, "ESCALADO")
                contagem[d["id"]] += 1
                semanas[d["id"]][cal_week] = semanas[d["id"]].get(cal_week, 0) + 1

        dias_gerados += 1

    return {
        "dias_gerados": dias_gerados,
        "avisos": avisos,
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
