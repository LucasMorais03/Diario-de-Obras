"""Ponto de entrada para servidores WSGI (gunicorn, waitress)."""
import os
from pathlib import Path

from diario import create_app
from diario.db import agora_utc, conectar, init_db, transacao
from diario.security import hash_senha, senha_invalida

app = create_app()


def _bootstrap_admin() -> None:
    nome = os.environ.get("BOOTSTRAP_ADMIN_NOME", "").strip()
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    senha = os.environ.get("BOOTSTRAP_ADMIN_SENHA", "")

    print(f"[BOOTSTRAP] nome={bool(nome)} email={email!r} senha={bool(senha)}", flush=True)

    if not (nome and email and senha):
        return

    erro_senha = senha_invalida(senha)
    if erro_senha:
        print(f"[BOOTSTRAP] Ignorado: {erro_senha}", flush=True)
        return

    db_path = Path(app.config["DATABASE"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[BOOTSTRAP] Banco em: {db_path.resolve()}", flush=True)

    db = conectar(str(db_path))
    try:
        init_db(db)
        with transacao(db):
            existe = db.execute("SELECT id, email FROM users LIMIT 1").fetchone()
            if existe:
                print(f"[BOOTSTRAP] Usuário já existe: {dict(existe)}", flush=True)
                return
            db.execute(
                "INSERT INTO users (nome, email, senha_hash, perfil, ativo, criado_em) "
                "VALUES (?, ?, ?, 'admin', 1, ?)",
                (nome[:150], email[:150], hash_senha(senha), agora_utc()),
            )
            db.execute(
                "INSERT INTO audit_log (ts, user_id, user_nome, acao, detalhe, ip) "
                "VALUES (?, NULL, ?, 'bootstrap_admin_criado', ?, NULL)",
                (agora_utc(), nome[:150], f"email={email[:150]}"),
            )
        print(f"[BOOTSTRAP] Admin criado com sucesso: {email}", flush=True)
    except Exception as exc:
        print(f"[BOOTSTRAP] ERRO: {exc!r}", flush=True)
        raise
    finally:
        db.close()


_bootstrap_admin()
