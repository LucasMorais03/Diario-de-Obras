"""Registro Diário de Obra: listagem com filtros, criação, detalhe, retificação e fotos."""
import os
import sqlite3
import uuid
from hashlib import sha256

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   send_from_directory, url_for)
from itsdangerous import BadSignature, URLSafeTimedSerializer

from . import security, services, utils
from .db import agora_utc, get_db

bp = Blueprint("rdos", __name__)
POR_PAGINA = 25
EXT = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def _serializador():
    return URLSafeTimedSerializer(current_app.secret_key, salt="form-rdo")


def _tipo_imagem(b: bytes):
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    return None


def _flt(v, lo, hi, padrao=None):
    try:
        x = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return padrao
    return x if lo <= x <= hi else padrao


def _like(q):
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# ------------------------------------------------------------------ listagem
@bp.get("/obras/<int:obra_id>/rdos")
@security.login_required
def lista(obra_id):
    obra = security.exigir_obra(obra_id)
    a = request.args
    ini = services.parse_data(a.get("inicio"), "")
    fim = services.parse_data(a.get("fim"), "")
    q = a.get("q", "").strip()[:100]
    where, params = ["r.obra_id=?"], [obra_id]
    if ini:
        where.append("r.data_ref>=?"); params.append(ini)
    if fim:
        where.append("r.data_ref<=?"); params.append(fim)
    if a.get("autor", "").isdigit():
        where.append("r.autor_id=?"); params.append(int(a["autor"]))
    if a.get("so_ocorr"):
        where.append("EXISTS (SELECT 1 FROM ocorrencias o WHERE o.rdo_id=r.id)")
    if a.get("sem_loc"):
        where.append("r.loc_status != 'ok'")
    if q:
        like = _like(q)
        where.append("(r.observacoes LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM rdo_servicos s WHERE s.rdo_id=r.id AND "
                     "(s.descricao LIKE ? ESCAPE '\\' OR s.local LIKE ? ESCAPE '\\')) OR EXISTS (SELECT 1 FROM ocorrencias o "
                     "WHERE o.rdo_id=r.id AND o.descricao LIKE ? ESCAPE '\\'))")
        params += [like] * 4
    db = get_db()
    corpo = " WHERE " + " AND ".join(where)
    total = db.execute("SELECT COUNT(*) FROM rdos r" + corpo, params).fetchone()[0]
    pagina = max(1, int(a.get("p", 1))) if a.get("p", "1").isdigit() else 1
    linhas = [dict(r) for r in db.execute(
        services.SERIE_SELECT + corpo + " ORDER BY r.data_ref DESC LIMIT ? OFFSET ?",
        params + [POR_PAGINA, (pagina - 1) * POR_PAGINA])]
    ids = [r["id"] for r in linhas]
    extra = {}
    if ids:
        for r in db.execute(f"SELECT id, criado_em FROM rdos WHERE id IN ({','.join('?' * len(ids))})", ids):
            extra[r["id"]] = r["criado_em"]
    for r in linhas:
        r["compl"], _ = services.completude(r)
        r["criado_em"] = extra[r["id"]]
    autores = db.execute("SELECT DISTINCT autor_id, autor_nome FROM rdos WHERE obra_id=? ORDER BY autor_nome", (obra_id,)).fetchall()
    args = {k: v for k, v in a.items() if k != "p" and v}
    return render_template("rdo_lista.html", obra=obra, linhas=linhas, total=total, pagina=pagina,
                           paginas=max(1, -(-total // POR_PAGINA)), autores=autores, args=args)


# ------------------------------------------------------------------ criação
def _ler_formulario(form, ids_func):
    erros = []
    hoje = utils.hoje_local().isoformat()
    data_ref = services.parse_data(form.get("data_ref"), None)
    if not data_ref:
        erros.append("Informe a data do registro.")
    elif data_ref > hoje:
        erros.append("A data do registro não pode ser futura.")
    clima_m, clima_t, cond = form.get("clima_manha"), form.get("clima_tarde"), form.get("condicao")
    if clima_m not in services.CLIMAS or clima_t not in services.CLIMAS:
        erros.append("Informe as condições climáticas da manhã e da tarde.")
    if cond not in services.CONDICOES:
        erros.append("Informe a condição de trabalho.")
    horas = _flt(form.get("horas_improdutivas", "0") or "0", 0, 24)
    if horas is None:
        erros.append("Horas improdutivas devem estar entre 0 e 24.")
    extra = form.get("efetivo_extra", "0") or "0"
    extra = int(extra) if extra.isdigit() and int(extra) <= 500 else None
    if extra is None:
        erros.append("Efetivo adicional inválido (0 a 500).")

    servicos = []
    for d, loc, at in zip(form.getlist("serv_desc"), form.getlist("serv_local"), form.getlist("serv_ating")):
        if not d.strip():
            continue
        v = _flt(at, 0, 100)
        if v is None:
            erros.append(f"Atingimento inválido no serviço “{d.strip()[:40]}” (0 a 100).")
            continue
        servicos.append({"descricao": d.strip()[:300], "local": loc.strip()[:150], "atingimento": int(round(v))})
    equipamentos = []
    for n, h, s in zip(form.getlist("eq_nome"), form.getlist("eq_horas"), form.getlist("eq_sit")):
        if not n.strip():
            continue
        hh = _flt(h or "0", 0, 24)
        if hh is None or s not in services.SITUACOES_EQUIP:
            erros.append(f"Dados inválidos no equipamento “{n.strip()[:40]}”.")
            continue
        equipamentos.append({"nome": n.strip()[:150], "horas": hh, "situacao": s})
    ocorrencias = []
    for t, g_, d in zip(form.getlist("oc_tipo"), form.getlist("oc_grav"), form.getlist("oc_desc")):
        if not d.strip():
            continue
        if t not in services.TIPOS_OCORRENCIA or g_ not in services.GRAVIDADES:
            erros.append("Tipo ou gravidade de ocorrência inválidos.")
            continue
        ocorrencias.append({"tipo": t, "gravidade": g_, "descricao": d.strip()[:2000]})
    presencas = sorted({int(x) for x in form.getlist("presentes") if x.isdigit() and int(x) in ids_func})
    obs = form.get("observacoes", "").strip()[:4000]
    if not (servicos or ocorrencias or obs):
        erros.append("Registre ao menos um serviço, uma ocorrência ou uma observação.")

    lat, lon = _flt(form.get("lat"), -90, 90), _flt(form.get("lon"), -180, 180)
    status = form.get("loc_status", "nao_informada")
    if status not in services.LOC_STATUS:
        status = "nao_informada"
    if status == "ok" and (lat is None or lon is None):
        status = "indisponivel"
    if status != "ok":
        lat = lon = None
    prec = _flt(form.get("precisao"), 0, 100000)
    dados = {"data_ref": data_ref, "clima_manha": clima_m, "clima_tarde": clima_t, "condicao": cond,
             "horas_improdutivas": horas if horas is not None else 0, "efetivo_extra": extra or 0,
             "observacoes": obs, "servicos": servicos, "equipamentos": equipamentos, "presencas": presencas,
             "ocorrencias": ocorrencias, "lat": lat, "lon": lon, "precisao_m": prec if lat is not None else None,
             "loc_status": status}
    return dados, erros


def _salvar_fotos(files, legendas, erros):
    salvas = []
    cfg = current_app.config
    arquivos = [(f, l) for f, l in zip(files, legendas + [""] * len(files)) if f and f.filename]
    if len(arquivos) > cfg["MAX_FOTOS_POR_RDO"]:
        erros.append(f"No máximo {cfg['MAX_FOTOS_POR_RDO']} fotos por registro.")
        return salvas
    for f, leg in arquivos:
        b = f.read(cfg["MAX_FOTO_BYTES"] + 1)
        ext = _tipo_imagem(b)
        if len(b) > cfg["MAX_FOTO_BYTES"]:
            erros.append(f"A foto “{f.filename[:40]}” excede {cfg['MAX_FOTO_BYTES'] // (1024 * 1024)} MB.")
        elif not ext:
            erros.append(f"“{f.filename[:40]}” não é uma imagem JPG, PNG ou WebP válida.")
        else:
            nome = uuid.uuid4().hex + "." + ext
            with open(os.path.join(cfg["UPLOAD_DIR"], nome), "wb") as fh:
                fh.write(b)
            salvas.append({"arquivo": nome, "nome_original": os.path.basename(f.filename)[:150], "sha256": sha256(b).hexdigest(),
                           "tamanho": len(b), "legenda": leg.strip()[:200]})
    return salvas


def _apagar(fotos):
    for f in fotos:
        try:
            os.remove(os.path.join(current_app.config["UPLOAD_DIR"], f["arquivo"]))
        except OSError:
            pass


@bp.route("/obras/<int:obra_id>/rdos/novo", methods=["GET", "POST"])
@security.login_required
def novo(obra_id):
    obra = security.exigir_obra(obra_id)
    if obra["status"] == "concluida":
        flash("Esta obra está concluída e não aceita novos registros.", "erro")
        return redirect(url_for("obras.painel", obra_id=obra_id))
    db = get_db()
    funcs = db.execute("SELECT * FROM funcionarios WHERE obra_id=? AND ativo=1 ORDER BY equipe, nome", (obra_id,)).fetchall()
    form = request.form if request.method == "POST" else None
    erros = []
    if request.method == "POST":
        dados, erros = _ler_formulario(request.form, {f["id"] for f in funcs})
        if dados["data_ref"] and dados["data_ref"] < obra["data_inicio"]:
            erros.append("A data é anterior ao início da obra.")
        fotos = _salvar_fotos(request.files.getlist("foto"), request.form.getlist("foto_legenda"), erros)
        if not erros:
            try:
                dados["form_aberto_em"], dados["tempo_preenchimento_s"] = None, None
                try:
                    tk = _serializador().loads(request.form.get("form_token", ""), max_age=172800)
                    if tk.get("o") == obra_id and tk.get("u") == g.user["id"]:
                        dados["form_aberto_em"] = tk["t"]
                        seg = (utils.para_local(agora_utc()) - utils.para_local(tk["t"])).total_seconds()
                        dados["tempo_preenchimento_s"] = int(max(0, min(seg, 172800)))
                except BadSignature:
                    pass
                rid = services.criar_rdo(db, obra_id, g.user, dados, fotos,
                                         {"ip": request.remote_addr, "user_agent": request.headers.get("User-Agent")})
                security.audit("rdo_criado", f"obra={obra_id} rdo={rid} loc={dados['loc_status']}")
                flash("Registro salvo. Ele não pode mais ser alterado; use a retificação para correções.", "ok")
                return redirect(url_for("rdos.detalhe", rdo_id=rid, criado=1))
            except sqlite3.IntegrityError:
                _apagar(fotos)
                existente = db.execute("SELECT id FROM rdos WHERE obra_id=? AND data_ref=?", (obra_id, dados["data_ref"])).fetchone()
                if existente:
                    erros.append(f"Já existe o registro #{existente['id']} desta obra para {utils.f_data(dados['data_ref'])}. "
                                 "Abra-o e use a retificação para complementar.")
                else:
                    raise
        else:
            _apagar(fotos)
    token = _serializador().dumps({"o": obra_id, "u": g.user["id"], "t": agora_utc()})
    return render_template("rdo_form.html", obra=obra, funcs=funcs, form=form, token=token, erros=erros), (422 if erros else 200)


# ------------------------------------------------------------------ detalhe
def _carregar_rdo(rdo_id):
    db = get_db()
    r = db.execute("SELECT * FROM rdos WHERE id=?", (rdo_id,)).fetchone()
    if not r:
        abort(404)
    return security.exigir_obra(r["obra_id"]), r


def _contexto_rdo(obra, r):
    db = get_db()
    q = lambda sql: db.execute(sql, (r["id"],)).fetchall()
    return {
        "obra": obra, "r": r,
        "servicos": q("SELECT * FROM rdo_servicos WHERE rdo_id=? ORDER BY id"),
        "equipamentos": q("SELECT * FROM rdo_equipamentos WHERE rdo_id=? ORDER BY id"),
        "presentes": q("SELECT f.* FROM rdo_presencas p JOIN funcionarios f ON f.id=p.funcionario_id WHERE p.rdo_id=? ORDER BY f.nome"),
        "ocorrencias": q(f"SELECT o.*, {services.STATUS_ATUAL_SQL} AS status_atual FROM ocorrencias o WHERE o.rdo_id=? ORDER BY o.id"),
        "fotos": q("SELECT * FROM fotos WHERE rdo_id=? ORDER BY id"),
        "retificacoes": q("SELECT * FROM retificacoes WHERE rdo_id=? ORDER BY id"),
        "integro": services.hash_confere(db, r),
        "atraso": utils.atraso_dias(r["data_ref"], r["criado_em"]),
    }


@bp.get("/rdos/<int:rdo_id>")
@security.login_required
def detalhe(rdo_id):
    obra, r = _carregar_rdo(rdo_id)
    return render_template("rdo_detalhe.html", **_contexto_rdo(obra, r), limpar_rascunho=bool(request.args.get("criado")))


@bp.get("/rdos/<int:rdo_id>/imprimir")
@security.login_required
def imprimir(rdo_id):
    obra, r = _carregar_rdo(rdo_id)
    security.audit("rdo_impresso", f"rdo={rdo_id}")
    return render_template("rdo_imprimir.html", **_contexto_rdo(obra, r))


@bp.post("/rdos/<int:rdo_id>/retificar")
@security.login_required
def retificar(rdo_id):
    _obra, r = _carregar_rdo(rdo_id)
    texto = request.form.get("texto", "").strip()
    if len(texto) < 5:
        flash("Descreva a retificação (mínimo de 5 caracteres).", "erro")
    else:
        get_db().execute("INSERT INTO retificacoes (rdo_id, autor_id, autor_nome, criado_em, texto) VALUES (?,?,?,?,?)",
                         (rdo_id, g.user["id"], g.user["nome"], agora_utc(), texto[:2000]))
        security.audit("rdo_retificado", f"rdo={rdo_id}")
        flash("Retificação registrada; o registro original foi preservado.", "ok")
    return redirect(url_for("rdos.detalhe", rdo_id=rdo_id) + "#retificacoes")


@bp.get("/fotos/<int:foto_id>")
@security.login_required
def foto(foto_id):
    f = get_db().execute("SELECT f.*, r.obra_id FROM fotos f JOIN rdos r ON r.id=f.rdo_id WHERE f.id=?", (foto_id,)).fetchone()
    if not f:
        abort(404)
    security.exigir_obra(f["obra_id"])
    ext = f["arquivo"].rsplit(".", 1)[-1]
    return send_from_directory(current_app.config["UPLOAD_DIR"], f["arquivo"], mimetype=EXT.get(ext, "application/octet-stream"),
                               max_age=0)
