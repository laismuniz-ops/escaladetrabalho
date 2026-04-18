"""Conexão e inicialização do SQLite."""
import shutil
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "escala.db"
BACKUP_DIR = DB_PATH.parent / "backups"

# Debounce: evita criar vários backups em alterações rápidas seguidas
_ultimo_backup: float = 0.0
_DEBOUNCE_SEG = 30  # no máximo 1 backup a cada 30 segundos


def get_connection() -> sqlite3.Connection:
    """Retorna uma conexão com row_factory configurado."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def db_cursor():
    """Context manager para cursor com commit automático.
    Faz backup automático após alterações (debounce de 30s)."""
    global _ultimo_backup
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
        # Backup automático se houve alteração e passou o debounce
        if conn.total_changes > 0 and DB_PATH.exists():
            agora = time.time()
            if agora - _ultimo_backup >= _DEBOUNCE_SEG:
                _ultimo_backup = agora
                try:
                    fazer_backup()
                except Exception:
                    pass
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS entregadores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                ativo INTEGER NOT NULL DEFAULT 1,
                ordem INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS escala_entregadores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entregador_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                status TEXT NOT NULL,
                UNIQUE(entregador_id, data),
                FOREIGN KEY (entregador_id) REFERENCES entregadores(id) ON DELETE CASCADE
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_esc_entr_data ON escala_entregadores(data);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_esc_entr_id ON escala_entregadores(entregador_id);")


# ---------- Backup ----------

def fazer_backup() -> str:
    """Copia o banco para data/backups/. Mantém os últimos 60. Retorna o nome do arquivo."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    nome = f"escala_{ts}.db"
    shutil.copy2(DB_PATH, BACKUP_DIR / nome)
    # Mantém só os últimos 60 backups
    backups = sorted(BACKUP_DIR.glob("escala_*.db"))
    for old in backups[:-60]:
        old.unlink()
    return nome


def listar_backups() -> list[dict]:
    """Retorna lista de backups do mais recente para o mais antigo."""
    if not BACKUP_DIR.exists():
        return []
    backups = sorted(BACKUP_DIR.glob("escala_*.db"), reverse=True)
    result = []
    for b in backups:
        stat = b.stat()
        result.append({
            "nome": b.name,
            "tamanho_kb": round(stat.st_size / 1024, 1),
            "criado_em": datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M:%S"),
        })
    return result


def restaurar_backup(nome: str) -> None:
    """Substitui o banco pelo backup escolhido."""
    if not nome.startswith("escala_") or not nome.endswith(".db") or "/" in nome or "\\" in nome:
        raise ValueError("Nome de backup inválido")
    backup = BACKUP_DIR / nome
    if not backup.exists():
        raise ValueError("Backup não encontrado")
    # Salva o estado atual antes de restaurar
    fazer_backup()
    shutil.copy2(backup, DB_PATH)
