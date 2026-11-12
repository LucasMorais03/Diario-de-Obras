"""Login, logout e troca de senha."""
from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from . import security
from .db import get_db

bp = Blueprint("auth", __name__)


@bp.get("/")
def raiz():
    return redirect(url_for("obras.lista" if g.user else "auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("obras.lista"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        if security.bloqueado(email):
            flash("Muitas tentativas sem sucesso. Aguarde alguns minutos e tente novamente.", "erro")
        else:
            u = security.autenticar(email, senha)
            if u:
                session.clear()
                session.permanent = True
                session["uid"] = u["id"]
                security.audit("login", user=u)
                destino = request.args.get("next", "")
                if not destino.startswith("/") or destino.startswith("//"):
                    destino = url_for("obras.lista")
                return redirect(destino)
            flash("E-mail ou senha incorretos.", "erro")
    return render_template("login.html")


@bp.post("/logout")
def logout():
    if g.user:
        security.audit("logout")
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/senha", methods=["GET", "POST"])
@security.login_required
def trocar_senha():
    if request.method == "POST":
        from werkzeug.security import check_password_hash
        atual, nova = request.form.get("atual", ""), request.form.get("nova", "")
        if not check_password_hash(g.user["senha_hash"], atual):
            flash("A senha atual não confere.", "erro")
        elif (msg := security.senha_invalida(nova)):
            flash(msg, "erro")
        else:
            get_db().execute("UPDATE users SET senha_hash=? WHERE id=?", (security.hash_senha(nova), g.user["id"]))
            security.audit("senha_alterada")
            flash("Senha alterada com sucesso.", "ok")
            return redirect(url_for("obras.lista"))
    return render_template("senha.html")
