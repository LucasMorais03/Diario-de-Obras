"""Obras, painel (dashboards), funcionários, ocorrências, relatórios, exportação e integridade."""
import csv
import io
from datetime import timedelta

from flask import Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, url_for

from . import charts, security, services, utils
from .db import agora_utc, get_db

bp = Blueprint("obras", __name__)
GESTAO = ("admin", "gestor")


# ------------------------------------------------------------------ lista e cadastro
@bp.get("/obras")
@security.login_required
def lista():
    db = get_db()
    obras = security.obras_do_usuario()
    ids = [o["id"] for o in obras]
    ultimo, abertas = {}, {}
    if ids:
        marc = ",".join("?" * len(ids))
        for r in db.execute(f"SELECT obra_id, MAX(data_ref) d FROM rdos WHERE obra_id IN ({marc}) GROUP BY obra_id", ids):
            ultimo[r["obra_id"]] = r["d"]
        for r in db.execute(
            f"SELECT o.obra_id, COUNT(*) n FROM ocorrencias o WHERE o.obra_id IN ({marc}) "
            f"AND {services.STATUS_ATUAL_SQL} != 'resolvida' GROUP BY o.obra_id", ids):
            abertas[r["obra_id"]] = r["n"]
    return render_template("obras_lista.html", obras=obras, ultimo=ultimo, abertas=abertas)


@bp.route("/obras/nova", methods=["GET", "POST"])
@security.perfil_required(*GESTAO)
def nova():
    if request.method == "POST":
        f = request.form
        nome = f.get("nome", "").strip()
        inicio = services.parse_data(f.get("data_inicio"), None)
        fim = services.parse_data(f.get("data_prevista_fim"), None) if f.get("data_prevista_fim") else None
        if not nome or not inicio:
            flash("Informe o nome da obra e uma data de início válida.", "erro")
        elif fim and fim < inicio:
            flash("A data prevista de término não pode ser anterior ao início.", "erro")
        else:
            db = get_db()
            oid = db.execute(
                "INSERT INTO obras (nome, endereco, responsavel, data_inicio, data_prevista_fim, status, criado_em) VALUES (?,?,?,?,?,?,?)",
                (nome[:200], f.get("endereco", "").strip()[:300], f.get("responsavel", "").strip()[:150], inicio, fim,
                 "em_andamento", agora_utc())).lastrowid
            db.execute("INSERT OR IGNORE INTO obra_usuarios (obra_id, user_id) VALUES (?,?)", (oid, g.user["id"]))
            security.audit("obra_criada", f"obra={oid} {nome}")
            flash("Obra cadastrada.", "ok")
            return redirect(url_for("obras.painel", obra_id=oid))
    return render_template("obra_form.html")


# ------------------------------------------------------------------ painel / dashboards
def _periodo():
    hoje = utils.hoje_local()
    ini = services.parse_data(request.args.get("inicio"), None)
    fim = services.parse_data(request.args.get("fim"), None)
    if not (ini and fim):
        dias = request.args.get("dias", "30")
        dias = int(dias) if dias in ("7", "30", "90") else 30
        fim, ini = hoje.isoformat(), (hoje - timedelta(days=dias - 1)).isoformat()
    if ini > fim:
        ini, fim = fim, ini
    return ini, fim


@bp.get("/obras/<int:obra_id>")
@security.login_required
def painel(obra_id):
    obra = security.exigir_obra(obra_id)
    ini, fim = _periodo()
    cfg = current_app.config
    r = services.resumo_obra(get_db(), obra, ini, fim, cfg["META_ATINGIMENTO"], cfg["LIMITE_HORAS_CLIMA"])
    rot = lambda row: row["data_ref"][8:10] + "/" + row["data_ref"][5:7]
    grafs = {
        "ating": charts.linha_svg([(rot(x), x["ating"]) for x in r["linhas"]], 100, cfg["META_ATINGIMENTO"], "Atingimento da meta diária (%)"),
        "clima": charts.barras_svg([(rot(x), x["horas_improdutivas"]) for x in r["linhas"]], " h", "Horas improdutivas por clima",
                                   "g-barra-clima", lambda v: v >= cfg["LIMITE_HORAS_CLIMA"]),
        "efetivo": charts.barras_svg([(rot(x), x["efetivo"]) for x in r["linhas"]], "", "Efetivo por dia"),
    }
    return render_template("obra_painel.html", obra=obra, r=r, grafs=grafs, ini=ini, fim=fim,
                           meta=cfg["META_ATINGIMENTO"], limite_horas=cfg["LIMITE_HORAS_CLIMA"])


@bp.get("/obras/<int:obra_id>/relatorio")
@security.login_required
def relatorio(obra_id):
    obra = security.exigir_obra(obra_id)
    ini, fim = _periodo()
    cfg = current_app.config
    r = services.resumo_obra(get_db(), obra, ini, fim, cfg["META_ATINGIMENTO"], cfg["LIMITE_HORAS_CLIMA"])
    rot = lambda row: row["data_ref"][8:10] + "/" + row["data_ref"][5:7]
    graf = charts.linha_svg([(rot(x), x["ating"]) for x in r["linhas"]], 100, cfg["META_ATINGIMENTO"], "Atingimento da meta diária (%)")
    security.audit("relatorio_gerado", f"obra={obra_id} {ini}..{fim}")
    return render_template("relatorio.html", obra=obra, r=r, graf=graf, ini=ini, fim=fim, meta=cfg["META_ATINGIMENTO"],
                           gerado_em=agora_utc())


def _csv_seguro(v):
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@bp.get("/obras/<int:obra_id>/export.csv")
@security.login_required
def exportar(obra_id):
    obra = security.exigir_obra(obra_id)
    ini, fim = _periodo()
    linhas = get_db().execute(services.SERIE_SELECT + " WHERE r.obra_id=? AND r.data_ref BETWEEN ? AND ? ORDER BY r.data_ref",
                              (obra_id, ini, fim)).fetchall()
    full = {r["id"]: r for r in get_db().execute("SELECT id, criado_em, hash FROM rdos WHERE obra_id=?", (obra_id,))}
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["data", "autor", "clima_manha", "clima_tarde", "condicao", "horas_improdutivas", "efetivo",
                "atingimento_medio", "ocorrencias", "fotos", "localizacao", "registrado_em", "hash"])
    for r in linhas:
        w.writerow([_csv_seguro(x) for x in (
            r["data_ref"], r["autor_nome"], services.CLIMAS[r["clima_manha"]], services.CLIMAS[r["clima_tarde"]],
            services.CONDICOES[r["condicao"]], f"{r['horas_improdutivas']:g}".replace(".", ","), r["efetivo"],
            "" if r["ating"] is None else f"{r['ating']:.0f}", r["n_ocorr"], r["n_fotos"], services.LOC_STATUS[r["loc_status"]],
            utils.f_dt(full[r["id"]]["criado_em"]), full[r["id"]]["hash"])])
    security.audit("export_csv", f"obra={obra_id} {ini}..{fim}")
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=rdos_obra{obra_id}_{ini}_{fim}.csv"})


# ------------------------------------------------------------------ integridade
@bp.get("/obras/<int:obra_id>/integridade")
@security.perfil_required(*GESTAO)
def integridade(obra_id):
    obra = security.exigir_obra(obra_id)
    res = services.verificar_cadeia(get_db(), obra_id, current_app.config["UPLOAD_DIR"])
    security.audit("integridade_verificada", f"obra={obra_id} ok={res['ok']}")
    return render_template("integridade.html", obra=obra, res=res)


# ------------------------------------------------------------------ funcionários e equipes
@bp.route("/obras/<int:obra_id>/funcionarios", methods=["GET", "POST"])
@security.login_required
def funcionarios(obra_id):
    obra = security.exigir_obra(obra_id)
    db = get_db()
    if request.method == "POST":
        if g.user["perfil"] not in GESTAO:
            abort(403)
        nome, funcao = request.form.get("nome", "").strip(), request.form.get("funcao", "").strip()
        equipe = request.form.get("equipe", "").strip()
        if not nome or not funcao:
            flash("Informe nome e função.", "erro")
        else:
            db.execute("INSERT INTO funcionarios (obra_id, nome, funcao, equipe) VALUES (?,?,?,?)",
                       (obra_id, nome[:150], funcao[:100], equipe[:100]))
            security.audit("funcionario_criado", f"obra={obra_id} {nome}")
            flash("Funcionário cadastrado.", "ok")
        return redirect(url_for("obras.funcionarios", obra_id=obra_id))
    lista_f = db.execute("SELECT * FROM funcionarios WHERE obra_id=? ORDER BY ativo DESC, equipe, nome", (obra_id,)).fetchall()
    return render_template("funcionarios.html", obra=obra, funcionarios=lista_f)


@bp.post("/obras/<int:obra_id>/funcionarios/<int:fid>/alternar")
@security.perfil_required(*GESTAO)
def alternar_funcionario(obra_id, fid):
    security.exigir_obra(obra_id)
    db = get_db()
    db.execute("UPDATE funcionarios SET ativo = 1 - ativo WHERE id=? AND obra_id=?", (fid, obra_id))
    security.audit("funcionario_alternado", f"obra={obra_id} func={fid}")
    return redirect(url_for("obras.funcionarios", obra_id=obra_id))


# ------------------------------------------------------------------ ocorrências
@bp.get("/obras/<int:obra_id>/ocorrencias")
@security.login_required
def ocorrencias(obra_id):
    obra = security.exigir_obra(obra_id)
    status = request.args.get("status", "")
    grav = request.args.get("gravidade", "")
    sql = (f"SELECT o.*, {services.STATUS_ATUAL_SQL} AS status_atual, r.data_ref FROM ocorrencias o "
           "JOIN rdos r ON r.id=o.rdo_id WHERE o.obra_id=?")
    params = [obra_id]
    if grav in services.GRAVIDADES:
        sql += " AND o.gravidade=?"
        params.append(grav)
    linhas = get_db().execute(sql + " ORDER BY r.data_ref DESC, o.id DESC", params).fetchall()
    if status in services.STATUS_OCORR:
        linhas = [o for o in linhas if o["status_atual"] == status]
    return render_template("ocorrencias.html", obra=obra, linhas=linhas, status=status, grav=grav)


@bp.route("/ocorrencias/<int:oid>", methods=["GET", "POST"])
@security.login_required
def ocorrencia(oid):
    db = get_db()
    oc = db.execute(f"SELECT o.*, {services.STATUS_ATUAL_SQL} AS status_atual, r.data_ref FROM ocorrencias o "
                    "JOIN rdos r ON r.id=o.rdo_id WHERE o.id=?", (oid,)).fetchone()
    if not oc:
        abort(404)
    obra = security.exigir_obra(oc["obra_id"])
    if request.method == "POST":
        texto = request.form.get("texto", "").strip()
        novo = request.form.get("novo_status") or None
        if novo and novo not in services.STATUS_OCORR:
            abort(400)
        if len(texto) < 3:
            flash("Descreva a atualização (mínimo de 3 caracteres).", "erro")
        else:
            db.execute("INSERT INTO ocorrencia_updates (ocorrencia_id, autor_id, autor_nome, criado_em, texto, novo_status) "
                       "VALUES (?,?,?,?,?,?)", (oid, g.user["id"], g.user["nome"], agora_utc(), texto[:2000], novo))
            security.audit("ocorrencia_atualizada", f"ocorrencia={oid} status={novo}")
            flash("Atualização registrada.", "ok")
            return redirect(url_for("obras.ocorrencia", oid=oid))
    updates = db.execute("SELECT * FROM ocorrencia_updates WHERE ocorrencia_id=? ORDER BY id", (oid,)).fetchall()
    return render_template("ocorrencia.html", obra=obra, oc=oc, updates=updates)
