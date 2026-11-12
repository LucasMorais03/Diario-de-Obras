"""Regras de negócio: criação de RDOs com cadeia de hashes, verificação e métricas."""
import hashlib
import json
import os
from datetime import date, datetime, timedelta

from .db import agora_utc, transacao

CLIMAS = {"ensolarado": "Ensolarado", "nublado": "Nublado", "chuva_fraca": "Chuva fraca", "chuva_forte": "Chuva forte"}
CONDICOES = {"praticavel": "Praticável", "parcial": "Parcialmente praticável", "impraticavel": "Impraticável"}
SITUACOES_EQUIP = {"operando": "Operando", "parado": "Parado", "manutencao": "Em manutenção"}
TIPOS_OCORRENCIA = {
    "acidente": "Acidente / quase acidente", "atraso": "Atraso", "falta_material": "Falta de material",
    "nao_conformidade": "Não conformidade", "interferencia_climatica": "Interferência climática", "outro": "Outro",
}
GRAVIDADES = {"baixa": "Baixa", "media": "Média", "alta": "Alta"}
STATUS_OCORR = {"aberta": "Aberta", "em_tratamento": "Em tratamento", "resolvida": "Resolvida"}
PERFIS = {"admin": "Administrador", "gestor": "Gestor", "campo": "Equipe de campo"}
STATUS_OBRA = {"em_andamento": "Em andamento", "paralisada": "Paralisada", "concluida": "Concluída"}
LOC_STATUS = {"ok": "Localização registrada", "negada": "Permissão de localização negada",
              "indisponivel": "Localização indisponível", "timeout": "Tempo esgotado ao obter localização",
              "nao_informada": "Localização não informada"}

# Status atual de uma ocorrência = último status registrado nas atualizações (padrão: aberta)
STATUS_ATUAL_SQL = ("COALESCE((SELECT u.novo_status FROM ocorrencia_updates u "
                    "WHERE u.ocorrencia_id=o.id AND u.novo_status IS NOT NULL ORDER BY u.id DESC LIMIT 1),'aberta')")


# ------------------------------------------------------------------ hash
def _num(v, casas=2):
    return None if v is None else round(float(v), casas)


def montar_payload(rdo, servicos, equipamentos, presencas, ocorrencias, fotos) -> dict:
    return {
        "obra_id": int(rdo["obra_id"]), "data_ref": rdo["data_ref"],
        "autor_id": int(rdo["autor_id"]), "autor_nome": rdo["autor_nome"],
        "criado_em": rdo["criado_em"], "form_aberto_em": rdo["form_aberto_em"] or "",
        "tempo": rdo["tempo_preenchimento_s"],
        "clima_manha": rdo["clima_manha"], "clima_tarde": rdo["clima_tarde"], "condicao": rdo["condicao"],
        "horas_improdutivas": _num(rdo["horas_improdutivas"]), "efetivo_extra": int(rdo["efetivo_extra"]),
        "observacoes": rdo["observacoes"] or "",
        "lat": _num(rdo["lat"], 7), "lon": _num(rdo["lon"], 7), "precisao_m": _num(rdo["precisao_m"]),
        "loc_status": rdo["loc_status"], "hash_anterior": rdo["hash_anterior"] or "",
        "servicos": [[s["descricao"], s["local"] or "", int(s["atingimento"])] for s in servicos],
        "equipamentos": [[e["nome"], _num(e["horas"]), e["situacao"]] for e in equipamentos],
        "presencas": sorted(int(p) for p in presencas),
        "ocorrencias": [[o["tipo"], o["gravidade"], o["descricao"]] for o in ocorrencias],
        "fotos": [[f["sha256"], f["legenda"] or ""] for f in fotos],
    }


def calcular_hash(payload: dict) -> str:
    bruto = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ criação
def criar_rdo(db, obra_id, autor, dados, fotos, meta) -> int:
    """Grava o RDO e seus itens numa única transação, encadeando o hash ao RDO anterior da obra.

    Levanta sqlite3.IntegrityError se já existir RDO da obra para a data.
    """
    with transacao(db):
        anterior = db.execute("SELECT hash FROM rdos WHERE obra_id=? ORDER BY id DESC LIMIT 1", (obra_id,)).fetchone()
        rdo = {
            "obra_id": obra_id, "data_ref": dados["data_ref"], "autor_id": autor["id"], "autor_nome": autor["nome"],
            "criado_em": dados.get("criado_em") or agora_utc(), "form_aberto_em": dados.get("form_aberto_em"),
            "tempo_preenchimento_s": dados.get("tempo_preenchimento_s"),
            "clima_manha": dados["clima_manha"], "clima_tarde": dados["clima_tarde"], "condicao": dados["condicao"],
            "horas_improdutivas": dados["horas_improdutivas"], "efetivo_extra": dados["efetivo_extra"],
            "observacoes": dados.get("observacoes") or "",
            "lat": dados.get("lat"), "lon": dados.get("lon"), "precisao_m": dados.get("precisao_m"),
            "loc_status": dados["loc_status"], "hash_anterior": anterior["hash"] if anterior else "",
        }
        payload = montar_payload(rdo, dados["servicos"], dados["equipamentos"], dados["presencas"],
                                 dados["ocorrencias"], fotos)
        rdo["hash"] = calcular_hash(payload)
        cols = list(rdo) + ["ip", "user_agent"]
        vals = list(rdo.values()) + [meta.get("ip"), (meta.get("user_agent") or "")[:300]]
        rid = db.execute(f"INSERT INTO rdos ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals).lastrowid
        for s in dados["servicos"]:
            db.execute("INSERT INTO rdo_servicos (rdo_id, descricao, local, atingimento) VALUES (?,?,?,?)",
                       (rid, s["descricao"], s["local"], s["atingimento"]))
        for e in dados["equipamentos"]:
            db.execute("INSERT INTO rdo_equipamentos (rdo_id, nome, horas, situacao) VALUES (?,?,?,?)",
                       (rid, e["nome"], e["horas"], e["situacao"]))
        for fid in dados["presencas"]:
            db.execute("INSERT INTO rdo_presencas (rdo_id, funcionario_id) VALUES (?,?)", (rid, fid))
        for o in dados["ocorrencias"]:
            db.execute("INSERT INTO ocorrencias (obra_id, rdo_id, tipo, gravidade, descricao, criado_em, autor_id, autor_nome) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (obra_id, rid, o["tipo"], o["gravidade"], o["descricao"], rdo["criado_em"], autor["id"], autor["nome"]))
        for f in fotos:
            db.execute("INSERT INTO fotos (rdo_id, arquivo, nome_original, sha256, tamanho, legenda, criado_em) "
                       "VALUES (?,?,?,?,?,?,?)",
                       (rid, f["arquivo"], f["nome_original"], f["sha256"], f["tamanho"], f["legenda"], rdo["criado_em"]))
        return rid


# ------------------------------------------------------------------ verificação
def sha256_arquivo(caminho: str) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(65536), b""):
            h.update(bloco)
    return h.hexdigest()


def _payload_do_banco(db, r):
    q = lambda sql: db.execute(sql, (r["id"],)).fetchall()
    fotos = q("SELECT * FROM fotos WHERE rdo_id=? ORDER BY id")
    payload = montar_payload(
        r, q("SELECT * FROM rdo_servicos WHERE rdo_id=? ORDER BY id"),
        q("SELECT * FROM rdo_equipamentos WHERE rdo_id=? ORDER BY id"),
        [p["funcionario_id"] for p in q("SELECT * FROM rdo_presencas WHERE rdo_id=?")],
        q("SELECT * FROM ocorrencias WHERE rdo_id=? ORDER BY id"), fotos)
    return payload, fotos


def hash_confere(db, r) -> bool:
    """Confere o hash de um único RDO (sem olhar o encadeamento)."""
    return calcular_hash(_payload_do_banco(db, r)[0]) == r["hash"]


def verificar_cadeia(db, obra_id, upload_dir=None) -> dict:
    """Recalcula cada hash a partir do conteúdo gravado e confere o encadeamento e os arquivos de foto."""
    problemas = []
    anterior = ""
    rdos = db.execute("SELECT * FROM rdos WHERE obra_id=? ORDER BY id", (obra_id,)).fetchall()
    for r in rdos:
        if (r["hash_anterior"] or "") != anterior:
            problemas.append((r["id"], "Encadeamento quebrado: o hash anterior não confere com o registro anterior."))
        payload, fotos = _payload_do_banco(db, r)
        if calcular_hash(payload) != r["hash"]:
            problemas.append((r["id"], "O conteúdo do registro não corresponde ao hash gravado (possível alteração)."))
        if upload_dir:
            for f in fotos:
                caminho = os.path.join(upload_dir, f["arquivo"])
                if not os.path.exists(caminho):
                    problemas.append((r["id"], f"Arquivo de foto ausente: {f['arquivo']}."))
                elif sha256_arquivo(caminho) != f["sha256"]:
                    problemas.append((r["id"], f"Arquivo de foto alterado: {f['arquivo']}."))
        anterior = r["hash"]
    return {"ok": not problemas, "total": len(rdos), "problemas": problemas}


# ------------------------------------------------------------------ métricas
def parse_data(valor, padrao):
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError):
        return padrao


def completude(r) -> tuple:
    """Quatro itens verificáveis automaticamente por RDO; devolve (percentual, faltantes)."""
    checks = [
        ("serviços executados", r["n_serv"] > 0),
        ("efetivo informado", r["efetivo"] > 0),
        ("localização registrada", r["loc_status"] == "ok"),
        ("registro fotográfico", r["n_fotos"] > 0),
    ]
    faltam = [nome for nome, ok in checks if not ok]
    return round(100 * (len(checks) - len(faltam)) / len(checks)), faltam


SERIE_SELECT = """
SELECT r.id, r.data_ref, r.autor_nome, r.condicao, r.clima_manha, r.clima_tarde, r.horas_improdutivas, r.loc_status,
  r.efetivo_extra + (SELECT COUNT(*) FROM rdo_presencas p WHERE p.rdo_id=r.id) AS efetivo,
  (SELECT COUNT(*) FROM rdo_servicos s WHERE s.rdo_id=r.id) AS n_serv,
  (SELECT AVG(s.atingimento) FROM rdo_servicos s WHERE s.rdo_id=r.id) AS ating,
  (SELECT COUNT(*) FROM fotos f WHERE f.rdo_id=r.id) AS n_fotos,
  (SELECT COUNT(*) FROM ocorrencias o WHERE o.rdo_id=r.id) AS n_ocorr
FROM rdos r
"""
SERIE_SQL = SERIE_SELECT + " WHERE r.obra_id=? AND r.data_ref BETWEEN ? AND ? ORDER BY r.data_ref"


def resumo_obra(db, obra, ini, fim, meta_ating, limite_horas) -> dict:
    linhas = [dict(r) for r in db.execute(SERIE_SQL, (obra["id"], ini, fim)).fetchall()]
    alertas = []
    for r in linhas:
        r["compl"], r["faltam"] = completude(r)
        if r["ating"] is not None and r["ating"] < meta_ating:
            alertas.append((r["data_ref"], r["id"], "Produtividade",
                            f"Atingimento médio de {r['ating']:.0f}% (meta {meta_ating}%)."))
        if r["horas_improdutivas"] >= limite_horas:
            alertas.append((r["data_ref"], r["id"], "Clima",
                            f"{r['horas_improdutivas']:g} h improdutivas ({CLIMAS[r['clima_manha']]} / {CLIMAS[r['clima_tarde']]})."))
    ocorr = db.execute(
        f"SELECT o.*, {STATUS_ATUAL_SQL} AS status_atual, r.data_ref FROM ocorrencias o JOIN rdos r ON r.id=o.rdo_id "
        "WHERE o.obra_id=? AND r.data_ref BETWEEN ? AND ? ORDER BY r.data_ref DESC, o.id DESC", (obra["id"], ini, fim)).fetchall()
    abertas = [o for o in ocorr if o["status_atual"] != "resolvida"]
    for o in abertas:
        if o["gravidade"] == "alta":
            alertas.append((o["data_ref"], o["rdo_id"], "Ocorrência", f"Ocorrência de gravidade alta ainda não resolvida: {TIPOS_OCORRENCIA[o['tipo']]}."))
    alertas.sort(reverse=True)

    hoje = date.today()
    d_ini = max(datetime.strptime(ini, "%Y-%m-%d").date(), datetime.strptime(obra["data_inicio"], "%Y-%m-%d").date())
    d_fim = min(datetime.strptime(fim, "%Y-%m-%d").date(), hoje)
    registrados = {r["data_ref"] for r in linhas}
    sem_registro = []
    if obra["status"] == "em_andamento":
        d = d_ini
        while d <= d_fim:
            if d.weekday() != 6 and d.isoformat() not in registrados:  # domingo não conta
                sem_registro.append(d.isoformat())
            d += timedelta(days=1)

    n = len(linhas)
    com_ating = [r["ating"] for r in linhas if r["ating"] is not None]
    por_tipo, por_grav = {}, {"baixa": 0, "media": 0, "alta": 0}
    for o in ocorr:
        por_tipo[o["tipo"]] = por_tipo.get(o["tipo"], 0) + 1
    for o in abertas:
        por_grav[o["gravidade"]] += 1
    return {
        "linhas": linhas, "n_rdos": n, "alertas": alertas, "ocorrencias": ocorr, "abertas": abertas,
        "ating_medio": sum(com_ating) / len(com_ating) if com_ating else None,
        "horas_total": sum(r["horas_improdutivas"] for r in linhas),
        "efetivo_medio": sum(r["efetivo"] for r in linhas) / n if n else None,
        "pct_loc": 100 * sum(r["loc_status"] == "ok" for r in linhas) / n if n else None,
        "pct_completos": 100 * sum(r["compl"] == 100 for r in linhas) / n if n else None,
        "sem_registro": sem_registro, "por_tipo": por_tipo, "por_grav": por_grav,
    }
