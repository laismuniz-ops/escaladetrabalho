"""Popula o banco com os dados de Abril/2026 extraídos dos PDFs originais.

Uso:
    python3 seed.py               # idempotente: pula funcionários já cadastrados
    python3 seed.py --reset       # apaga e recria tudo
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from app.database import db_cursor, init_db
from app.models import criar_funcionario, set_turno
from app.auth import criar_usuario

ANO = 2026
MES = 4

# ---------- Contratados ----------
# Cada lista de turnos corresponde aos dias 1..30 de abril/2026.
# Use F=Folga, M=Manhã, T=Tarde, V=Férias, "" = sem marcação
CONTRATADOS = [
    # (nome, cargo, setor, ordem, turnos[30])
    (
        "Roberta Campos", "Fiscal Cozinha", "COZINHA", 1,
        # 1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30
         ["F","T","T","T","F","T","T","F","T","T","T","T","T","T","F","F","T","T","F",
          "T","T","F","T","T","T","T","T","T","F","T"],
    ),
    (
        "Delvaney Gomes", "Sushiman", "COZINHA", 2,
         ["F","T","T","T","F","T","F","T","T","T","T","T","F","T","T","T","T","T","T",
          "T","T","F","T","T","T","T","T","T","F","T"],
    ),
    (
        "Rafael Basto", "Sushiman", "COZINHA", 3,
         ["T","T","T","T","T","T","T","F","T","T","T","F","T","T","F","T","T","T","T",
          "T","T","T","F","T","T","T","F","T","T","T"],
    ),
    (
        "Fabíola Pereira", "Aux. de Cozinha fria", "COZINHA", 4,
         ["T","T","T","T","T","T","F","T","T","T","T","F","T","F","T","T","T","T","T",
          "T","T","T","F","T","T","F","T","F","T","T"],
    ),
    (
        "Gabriel Mota", "Aux. de Cozinha quente", "COZINHA", 5,
         ["T","T","T","T","T","F","T","T","T","T","T","T","F","T","T","T","T","T","F",
          "T","F","T","T","T","T","T","F","T","T","T"],
    ),
    (
        "Cássio Ribeiro", "Sushiman de produção", "COZINHA", 6,
        # Dias 1-19 = FÉRIAS. Dia 20 sem marcação. 21-30 = M/M/F/M/M/M/M/F/M/M
         ["V","V","V","V","V","V","V","V","V","V","V","V","V","V","V","V","V","V","V",
          "", "M","M","F","M","M","M","M","F","M","M"],
    ),
    (
        "Matheus Oliveira", "Motoboy", "ATENDIMENTO", 7,
         ["T","T","T","T","T","T","F","T","T","T","T","T","T","F","T","T","T","T","T",
          "T","T","F","T","T","T","F","T","F","T","T"],
    ),
    (
        "Giannina", "Atendente", "ATENDIMENTO", 8,
        # Dias 1-14 sem marcação (entrou depois). 15-19: T/F/T/T/F. 20-30: T/T/F/T/T/T/T/T/F/T/T
         ["", "", "", "", "", "", "", "", "", "", "", "", "", "",
          "T","F","T","T","F",
          "T","T","F","T","T","T","T","T","F","T","T"],
    ),
    (
        "Jaqueline Paixão", "Analista de RH", "ADMINISTRATIVO", 9,
         ["M","M","F","F","F","M","M","M","M","M","F","F","M","M","M","M","M","F","F",
          "M","F","M","M","M","F","F","M","M","M","M"],
    ),
    (
        "Jéssica Carneiro", "Assistente de RH", "ADMINISTRATIVO", 10,
         ["M","M","F","M","F","M","M","M","M","M","M","F","M","M","M","M","M","M","F",
          "M","F","M","M","M","M","F","M","M","M","M"],
    ),
    (
        "Letícia Renata", "Auxiliar Administrativo", "ADMINISTRATIVO", 11,
         ["M","M","F","M","F","M","M","M","M","M","M","F","M","M","M","M","M","M","F",
          "M","F","M","M","M","M","F","M","M","M","M"],
    ),
    (
        "Joyce Botelho", "Analista Adm Financeiro", "ADMINISTRATIVO", 12,
         ["M","M","F","M","F","M","M","M","M","M","M","F","M","M","M","M","M","M","F",
          "M","F","M","M","M","M","F","M","M","M","M"],
    ),
]

# ---------- Extras ----------
# Cada entrada: (nome, cargo, setor, ordem, {dia_do_mes: turno})
# Turnos especiais ("Dia todo", "Noite") foram convertidos pra TARDE — ajuste depois se preferir
EXTRAS = [
    (
        "Extra Rafael Basto", "Sushiman", "COZINHA", 21,
        {14: "M", 17: "M"},
    ),
    (
        "Extra Delvaney", "Sushiman", "COZINHA", 22,
        {15: "M", 18: "M"},
    ),
    (
        "Extra Roberta", "Sushiman", "COZINHA", 23,
        {13: "M", 16: "M", 20: "M"},
    ),
    (
        "Extra Ruthe", "Aux. de Cozinha", "COZINHA", 24,
        {13: "T", 15: "T", 16: "T", 17: "T", 18: "T", 19: "T"},
    ),
    (
        "Extra Vitória", "Aux. de Cozinha", "COZINHA", 25,
        # 20=Dia todo (convertido p/ T), 21=Noite (convertido p/ T)
        {13: "T", 14: "T", 16: "M", 17: "T", 18: "T", 19: "T",
         20: "T", 21: "T", 23: "M", 26: "T", 27: "M"},
    ),
    (
        "Extra Natália", "Atendente", "ATENDIMENTO", 26,
        {14: "T", 16: "T", 17: "T", 18: "T", 19: "T",
         21: "T", 23: "T", 24: "T", 25: "T", 26: "T",
         28: "T", 30: "T"},
    ),
]

TURNO_MAP = {"M": "MANHA", "T": "TARDE", "F": "FOLGA", "V": "FERIAS"}


def reset_db() -> None:
    with db_cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS escala;")
        cur.execute("DROP TABLE IF EXISTS funcionarios;")


def _func_existe(nome: str) -> int | None:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM funcionarios WHERE nome = ?", (nome,))
        row = cur.fetchone()
        return row["id"] if row else None


def seed_contratados() -> None:
    for nome, cargo, setor, ordem, turnos in CONTRATADOS:
        existente = _func_existe(nome)
        if existente:
            print(f"  ~ {nome} já existe (id={existente}), pulando")
            continue
        fid = criar_funcionario(nome, cargo, setor, "CONTRATADO", ordem)
        for dia_idx, codigo in enumerate(turnos, start=1):
            if codigo == "":
                continue
            turno = TURNO_MAP[codigo]
            data_iso = date(ANO, MES, dia_idx).isoformat()
            set_turno(fid, data_iso, turno)
        print(f"  ✓ {nome} (id={fid})")


def seed_extras() -> None:
    for nome, cargo, setor, ordem, dias in EXTRAS:
        existente = _func_existe(nome)
        if existente:
            print(f"  ~ {nome} já existe (id={existente}), pulando")
            continue
        fid = criar_funcionario(nome, cargo, setor, "EXTRA", ordem)
        for dia, codigo in dias.items():
            turno = TURNO_MAP[codigo]
            data_iso = date(ANO, MES, dia).isoformat()
            set_turno(fid, data_iso, turno)
        print(f"  ✓ {nome} (id={fid})")


def seed_admin() -> None:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM usuarios WHERE username = 'admin'")
        if cur.fetchone():
            print("  ~ admin já existe, pulando")
            return
    criar_usuario(
        username="admin",
        nome="Administrador",
        senha="singular2026",
        is_admin=True,
        abas=[],
    )
    print("  ✓ admin criado (senha: singular2026) — troque depois!")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Apaga e recria todas as tabelas antes de popular",
    )
    args = parser.parse_args()

    if args.reset:
        print("⚠️  Resetando banco...")
        reset_db()

    print("→ Inicializando schema")
    init_db()
    print("→ Criando usuário admin")
    seed_admin()
    print("→ Importando contratados")
    seed_contratados()
    print("→ Importando extras")
    seed_extras()
    print("✅ Seed concluído.")


if __name__ == "__main__":
    main()
