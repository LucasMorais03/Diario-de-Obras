"""Diário de Obras Digital: aplicação Flask."""
import os
import secrets
from datetime import timedelta

from flask import Flask, g, render_template, request

from . import db as dbm
from . import security, services, utils


def _chave_secreta(app) -> str:
    chave = os.environ.get("DIARIO_SECRET_KEY")
    if chave:
        return chave
    caminho = os.path.join(app.instance_path, "secret_key")
    if not os.path.exists(caminho):
        with open(os.open(caminho, os.O_WRONLY | os.O_CREAT, 0o600), "w") as fh:
            fh.write(secrets.token_hex(32))
    with open(caminho) as fh:
        return fh.read().strip()


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.update(
        DATABASE=os.path.join(app.instance_path, "diario.sqlite"),
        UPLOAD_DIR=os.path.join(app.instance_path, "uploads"),
        MAX_CONTENT_LENGTH=40 * 1024 * 1024,
        MAX_FOTO_BYTES=8 * 1024 * 1024,
        MAX_FOTOS_POR_RDO=10,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("DIARIO_COOKIE_SECURE") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        META_ATINGIMENTO=int(os.environ.get("DIARIO_META_ATINGIMENTO", "70")),
        LIMITE_HORAS_CLIMA=float(os.environ.get("DIARIO_LIMITE_HORAS_CLIMA", "2")),
        TZ=os.environ.get("DIARIO_TZ", "America/Bahia"),
    )
    if config:
        app.config.update(config)
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)
    app.secret_key = app.config.get("SECRET_KEY") or _chave_secreta(app)

    app.teardown_appcontext(dbm.close_db)

    @app.before_request
    def antes():
        security.carregar_usuario()
        if request.method == "POST":
            security.verificar_csrf()

    @app.after_request
    def cabecalhos(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
        resp.headers["Permissions-Policy"] = "geolocation=(self), camera=(self)"
        if resp.mimetype == "text/html":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    app.jinja_env.filters.update(dt=utils.f_dt, data=utils.f_data, dec=utils.f_dec, atraso=lambda r: utils.atraso_dias(r["data_ref"], r["criado_em"]))

    @app.context_processor
    def contexto():
        return {
            "csrf_token": security.csrf_token, "usuario": g.get("user"),
            "R": {"clima": services.CLIMAS, "condicao": services.CONDICOES, "equip": services.SITUACOES_EQUIP,
                  "tipo": services.TIPOS_OCORRENCIA, "grav": services.GRAVIDADES, "status_oc": services.STATUS_OCORR,
                  "perfil": services.PERFIS, "status_obra": services.STATUS_OBRA, "loc": services.LOC_STATUS},
            "hoje": utils.hoje_local().isoformat(),
        }

    from . import admin, auth, obras, rdos
    for modulo in (auth, admin, obras, rdos):
        app.register_blueprint(modulo.bp)

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def erro_http(e):
        msgs = {400: "Requisição inválida.", 403: "Você não tem permissão para esta ação.",
                404: "Página ou registro não encontrado.", 413: "O envio excede o tamanho máximo permitido."}
        detalhe = e.description if e.code == 400 and e.description else msgs.get(e.code, "Erro.")
        return render_template("erro.html", codigo=e.code, mensagem=detalhe), e.code

    from . import cli
    cli.registrar(app)
    return app
