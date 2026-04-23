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


_ENTREGADORES_INICIAIS = [
    "André Ferreira", "Andre Oliveira", "Beatriz Araújo", "Breno Farias",
    "Carlos Alexandre", "Felipe Souza", "Fredy Gonzales", "Isaac Costa",
    "Luiz Gustavo", "Matheus Guedes", "Matheus Oliveira", "Mayke Martins",
    "Rafael Gama", "Ruben", "Sergio Sullivan", "Tanner Castro",
    "Thiago Felipe Weckner", "Uziel Alex",
]


def _seed_entregadores_if_empty(cur) -> None:
    """Cadastra os entregadores iniciais se a tabela estiver vazia."""
    cur.execute("SELECT COUNT(*) FROM entregadores")
    if cur.fetchone()[0] == 0:
        nomes = sorted(_ENTREGADORES_INICIAIS, key=lambda n: n.lower())
        for i, nome in enumerate(nomes):
            cur.execute(
                "INSERT INTO entregadores (nome, obs, cor, telefone, ordem) VALUES (?, '', '', '', ?)",
                (nome, i * 10),
            )


def _migrate_entregadores_if_needed(cur) -> None:
    """Adiciona colunas obs e cor à tabela entregadores e reordena alfabeticamente."""
    cur.execute("PRAGMA table_info(entregadores)")
    cols = [r["name"] for r in cur.fetchall()]
    if not cols:
        return  # tabela ainda não existe
    reordenar = False
    if "obs" not in cols:
        cur.execute("ALTER TABLE entregadores ADD COLUMN obs TEXT NOT NULL DEFAULT ''")
        reordenar = True
    if "cor" not in cols:
        cur.execute("ALTER TABLE entregadores ADD COLUMN cor TEXT NOT NULL DEFAULT ''")
    if reordenar:
        # Na primeira migração, reordena alfabeticamente
        cur.execute("SELECT id FROM entregadores ORDER BY LOWER(nome)")
        rows = cur.fetchall()
        for i, row in enumerate(rows):
            cur.execute("UPDATE entregadores SET ordem = ? WHERE id = ?", (i * 10, row["id"]))
    # Renomeia DEVAGAR → NORMAL (migração de nomenclatura)
    cur.execute("UPDATE entregadores SET cor = 'NORMAL' WHERE cor = 'DEVAGAR'")
    # Adiciona coluna telefone se não existir
    if "telefone" not in cols:
        cur.execute("ALTER TABLE entregadores ADD COLUMN telefone TEXT NOT NULL DEFAULT ''")


def _migrate_genero_if_needed(cur) -> None:
    """Adiciona coluna genero a funcionarios se não existir (M/F, default M)."""
    cur.execute("PRAGMA table_info(funcionarios)")
    cols = [r["name"] for r in cur.fetchall()]
    if cols and "genero" not in cols:
        cur.execute("ALTER TABLE funcionarios ADD COLUMN genero TEXT NOT NULL DEFAULT 'M'")


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
        _migrate_genero_if_needed(cur)
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
        _migrate_entregadores_if_needed(cur)
        _seed_entregadores_if_empty(cur)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS min_entregadores_dia (
                dia_semana INTEGER PRIMARY KEY,
                minimo     INTEGER NOT NULL DEFAULT 0
            );
        """)
        # Garante as 7 linhas (uma por dia da semana)
        for _d in range(7):
            cur.execute(
                "INSERT OR IGNORE INTO min_entregadores_dia (dia_semana, minimo) VALUES (?, 0)",
                (_d,),
            )
        cur.execute("""
            CREATE TABLE IF NOT EXISTS feriados (
                data TEXT PRIMARY KEY,
                nome TEXT NOT NULL
            );
        """)
        _seed_feriados_if_empty(cur)


_FERIADOS_BRASIL = [
    # 2025 — Nacionais
    ("2025-01-01","Ano Novo"),("2025-04-18","Sexta-feira Santa"),
    ("2025-04-20","Páscoa"),("2025-04-21","Tiradentes"),
    ("2025-05-01","Dia do Trabalhador"),("2025-06-19","Corpus Christi"),
    ("2025-09-07","Independência do Brasil"),("2025-10-12","Nossa Senhora Aparecida"),
    ("2025-11-02","Finados"),("2025-11-15","Proclamação da República"),
    ("2025-11-20","Consciência Negra"),("2025-12-25","Natal"),
    # 2026 — Nacionais
    ("2026-01-01","Ano Novo"),("2026-04-03","Sexta-feira Santa"),
    ("2026-04-05","Páscoa"),("2026-04-21","Tiradentes"),
    ("2026-05-01","Dia do Trabalhador"),("2026-06-04","Corpus Christi"),
    ("2026-09-07","Independência do Brasil"),("2026-10-12","Nossa Senhora Aparecida"),
    ("2026-11-02","Finados"),("2026-11-15","Proclamação da República"),
    ("2026-11-20","Consciência Negra"),("2026-12-25","Natal"),
    # 2027 — Nacionais
    ("2027-01-01","Ano Novo"),("2027-03-26","Sexta-feira Santa"),
    ("2027-03-28","Páscoa"),("2027-04-21","Tiradentes"),
    ("2027-05-01","Dia do Trabalhador"),("2027-06-17","Corpus Christi"),
    ("2027-09-07","Independência do Brasil"),("2027-10-12","Nossa Senhora Aparecida"),
    ("2027-11-02","Finados"),("2027-11-15","Proclamação da República"),
    ("2027-11-20","Consciência Negra"),("2027-12-25","Natal"),
]

# Feriados estaduais (Amazonas) + municipais (Manaus)
# Sempre inseridos com INSERT OR IGNORE → seguros de re-executar
_FERIADOS_MANAUS = [
    # 2025
    ("2025-09-05","Elevação do Amazonas à Categoria de Província"),
    ("2025-10-24","Fundação de Manaus"),
    # 2026
    ("2026-09-05","Elevação do Amazonas à Categoria de Província"),
    ("2026-10-24","Fundação de Manaus"),
    # 2027
    ("2027-09-05","Elevação do Amazonas à Categoria de Província"),
    ("2027-10-24","Fundação de Manaus"),
]


def _seed_feriados_if_empty(cur) -> None:
    cur.execute("SELECT COUNT(*) FROM feriados")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT OR IGNORE INTO feriados (data, nome) VALUES (?,?)", _FERIADOS_BRASIL)
    # Feriados de Manaus/AM sempre garantidos (INSERT OR IGNORE = idempotente)
    cur.executemany("INSERT OR IGNORE INTO feriados (data, nome) VALUES (?,?)", _FERIADOS_MANAUS)


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
