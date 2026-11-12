"""Acesso ao SQLite, transações e proteção contra alteração de registros."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g

# Tabelas cujo conteúdo nunca pode ser alterado ou apagado depois de gravado.
# Correções são feitas por retificações e atualizações (também append-only).
IMUTAVEIS = [
    "rdos", "rdo_servicos", "rdo_equipamentos", "rdo_presencas", "ocorrencias",
    "ocorrencia_updates", "fotos", "retificacoes", "audit_log",
]


def agora_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def conectar(caminho: str) -> sqlite3.Connection:
    con = sqlite3.connect(caminho, isolation_level=None, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = conectar(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def transacao(db: sqlite3.Connection):
    """Transação explícita; BEGIN IMMEDIATE evita corrida na cadeia de hashes."""
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


def init_db(db: sqlite3.Connection) -> None:
    db.executescript((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))
    for tabela in IMUTAVEIS:
        for op in ("UPDATE", "DELETE"):
            db.execute(
                f"CREATE TRIGGER IF NOT EXISTS {tabela}_no_{op.lower()} "
                f"BEFORE {op} ON {tabela} BEGIN "
                f"SELECT RAISE(ABORT, 'Registro imutável: use retificação.'); END"
            )
