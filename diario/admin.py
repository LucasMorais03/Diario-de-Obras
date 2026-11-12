"""Administração de usuários, vínculos com obras e trilha de auditoria."""
import sqlite3

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from . import security
from .db import agora_utc, get_db
from .services import PERFIS

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.get("/usuarios")
@security.perfil_required("admin")
def usuarios():
    linhas = get_db().execute(
        "SELECT u.*, (SELECT COUNT(*) FROM obra_usuarios ou WHERE ou.user_id=u.id) AS n_obras FROM users u ORDER BY u.ativo DESC, u.nome"
    ).fetchall()
    return render_template("admin_usuarios.html", usuarios=linhas)


@bp.route("/usuarios/novo", methods=["GET", "POST"])
@bp.route("/usuarios/<int:uid>", methods=["GET", "POST"])
@security.perfil_required("admin")
def usuario(uid=None):
    db = get_db()
    alvo = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if uid and not alvo:
        abort(404)
    obras = db.execute("SELECT id, nome FROM obras ORDER BY nome").fetchall()
    vinculadas = {r["obra_id"] for r in db.execute("SELECT obra_id FROM obra_usuarios WHERE user_id=?", (uid,))} if uid else set()
    if request.method == "POST":
        f = request.form
        nome, email = f.get("nome", "").strip(), f.get("email", "").strip().lower()
        perfil, senha = f.get("perfil", ""), f.get("senha", "")
        ativo = 1 if f.get("ativo") else 0
        erro = None
        if not nome or "@" not in email:
            erro = "Informe nome e um e-mail válido."
        elif perfil not in PERFIS:
            erro = "Perfil inválido."
        elif (not alvo or senha) and (erro := security.senha_invalida(senha)):
            pass
        elif alvo and alvo["id"] == g.user["id"] and (not ativo or perfil != "admin"):
            erro = "Você não pode desativar nem rebaixar a própria conta."
        if erro:
            flash(erro, "erro")
        else:
            try:
                if alvo:
                    db.execute("UPDATE users SET nome=?, email=?, perfil=?, ativo=? WHERE id=?", (nome, email, perfil, ativo, uid))
                    if senha:
                        db.execute("UPDATE users SET senha_hash=? WHERE id=?", (security.hash_senha(senha), uid))
                    security.audit("usuario_editado", f"{email} ({perfil}, ativo={ativo})")
                else:
                    uid = db.execute("INSERT INTO users (nome,email,senha_hash,perfil,ativo,criado_em) VALUES (?,?,?,?,?,?)",
                                     (nome, email, security.hash_senha(senha), perfil, 1, agora_utc())).lastrowid
                    security.audit("usuario_criado", f"{email} ({perfil})")
                db.execute("DELETE FROM obra_usuarios WHERE user_id=?", (uid,))
                for oid in f.getlist("obras"):
                    if oid.isdigit():
                        db.execute("INSERT OR IGNORE INTO obra_usuarios (obra_id,user_id) VALUES (?,?)", (int(oid), uid))
                flash("Usuário salvo.", "ok")
                return redirect(url_for("admin.usuarios"))
            except sqlite3.IntegrityError:
                flash("Já existe um usuário com este e-mail.", "erro")
    return render_template("admin_usuario.html", alvo=alvo, obras=obras, vinculadas=vinculadas)


@bp.get("/auditoria")
@security.perfil_required("admin")
def auditoria():
    linhas = get_db().execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 300").fetchall()
    return render_template("admin_auditoria.html", linhas=linhas)
