"""Conexão e inicialização do SQLite."""
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "escala.db"


def get_connection() -> sqlite3.Connection:
    """Retorna uma conexão com row_factory configurado."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def db_cursor():
    """Context manager para cursor com commit automático."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_minimos_if_needed(cur) -> None:
    """Adiciona coluna dia_semana em minimos_escala se não existir."""
    cur.execute("PRAGMA table_info(minimos_escala)")
    cols = [r["name"] for r in cur.fetchall()]
    if not cols:
        return  # tabela ainda não existe
    if "dia_semana" not in cols:
        # Lê valores atuais
        cur.execute("SELECT setor, turno, minimo FROM minimos_escala")
        rows = cur.fetchall()
        # Recria tabela com dia_semana na PK
        cur.execute("""
            CREATE TABLE minimos_escala_new (
                setor TEXT NOT NULL,
                turno TEXT NOT NULL,
                dia_semana INTEGER NOT NULL DEFAULT 0,
                minimo INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (setor, turno, dia_semana)
            )
        """)
        # Copia dados expandindo para os 7 dias
        for row in rows:
            for dia in range(7):
                cur.execute(
                    "INSERT INTO minimos_escala_new VALUES (?, ?, ?, ?)",
                    (row["setor"], row["turno"], dia, row["minimo"]),
                )
        cur.execute("DROP TABLE minimos_escala")
        cur.execute("ALTER TABLE minimos_escala_new RENAME TO minimos_escala")


def _migrate_escala_if_needed(cur) -> None:
    """Recria a tabela escala removendo o CHECK de turno (suporte a turnos compostos)."""
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='escala'")
    row = cur.fetchone()
    if row and "CHECK" in row[0]:
        # Remove o CHECK para permitir valores compostos como 'MANHA+TARDE'
        cur.execute("""
            CREATE TABLE escala_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                funcionario_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                turno TEXT NOT NULL,
                observacao TEXT,
                UNIQUE(funcionario_id, data),
                FOREIGN KEY (funcionario_id) REFERENCES funcionarios(id) ON DELETE CASCADE
            )
        """)
        cur.execute("INSERT INTO escala_new SELECT * FROM escala")
        cur.execute("DROP TABLE escala")
        cur.execute("ALTER TABLE escala_new RENAME TO escala")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_escala_data ON escala(data)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_escala_func ON escala(funcionario_id)")


def init_db() -> None:
    """Cria as tabelas se não existirem."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db_cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS funcionarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                cargo TEXT NOT NULL,
                setor TEXT NOT NULL,
                tipo TEXT NOT NULL CHECK (tipo IN ('CONTRATADO', 'EXTRA')),
                ativo INTEGER NOT NULL DEFAULT 1,
                ordem INTEGER NOT NULL DEFAULT 0,
                criado_em TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS escala (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                funcionario_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                turno TEXT NOT NULL CHECK (turno IN ('MANHA', 'TARDE', 'FOLGA', 'FERIAS', 'AFASTAMENTO')),
                observacao TEXT,
                UNIQUE(funcionario_id, data),
                FOREIGN KEY (funcionario_id) REFERENCES funcionarios(id) ON DELETE CASCADE
            );
            """
        )
        # Migração: recria tabela escala se ainda tiver o CHECK antigo (sem AFASTAMENTO)
        cur.execute("PRAGMA table_info(escala)")
        _migrate_escala_if_needed(cur)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_escala_data ON escala(data);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_escala_func ON escala(funcionario_id);"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                nome TEXT NOT NULL,
                senha_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                abas_permitidas TEXT NOT NULL DEFAULT '[]',
                ativo INTEGER NOT NULL DEFAULT 1,
                criado_em TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS notas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                funcionario_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                texto TEXT NOT NULL DEFAULT '',
                UNIQUE(funcionario_id, data),
                FOREIGN KEY (funcionario_id) REFERENCES funcionarios(id) ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_notas_func ON notas(funcionario_id);"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS minimos_escala (
                setor TEXT NOT NULL,
                turno TEXT NOT NULL,
                dia_semana INTEGER NOT NULL DEFAULT 0,
                minimo INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (setor, turno, dia_semana)
            );
            """
        )
        _migrate_minimos_if_needed(cur)
