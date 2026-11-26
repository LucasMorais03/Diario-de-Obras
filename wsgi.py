"""Ponto de entrada para servidores WSGI (gunicorn, waitress)."""
import os

from diario import create_app
from diario.db import agora_utc, conectar, init_db, transacao
from diario.security import hash_senha, senha_invalida

app = create_app()


def _bootstrap_admin() -> None:
    nome = os.environ.get("BOOTSTRAP_ADMIN_NOME", "").strip()
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    senha = os.environ.get("BOOTSTRAP_ADMIN_SENHA", "")

    if not (nome and email and senha):
        return

    erro_senha = senha_invalida(senha)
    if erro_senha:
        app.logger.warning("Bootstrap de admin ignorado: %s", erro_senha)
        return

    db = conectar(app.config["DATABASE"])
    try:
        init_db(db)
        with transacao(db):
            existe = db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
            if existe:
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
        app.logger.info("Administrador inicial criado via bootstrap (%s).", email)
    finally:
        db.close()


_bootstrap_admin()