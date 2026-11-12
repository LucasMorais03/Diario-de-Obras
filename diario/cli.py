"""Comandos de linha: init-db, create-admin e seed-demo."""
import os
import random
import struct
import uuid
import zlib
from datetime import datetime, time, timedelta, timezone
from hashlib import sha256

import click

from . import db as dbm
from . import security, services, utils


def _png(largura, altura, cor):
    """PNG sólido mínimo (sem dependências), usado só nas fotos de demonstração."""
    linha = b"\x00" + bytes(cor) * largura
    bruto = linha * altura

    def bloco(tag, dados):
        corpo = tag + dados
        return struct.pack(">I", len(dados)) + corpo + struct.pack(">I", zlib.crc32(corpo) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0))
            + bloco(b"IDAT", zlib.compress(bruto, 9)) + bloco(b"IEND", b""))


def registrar(app):
    @app.cli.command("init-db")
    def init_db_cmd():
        """Cria as tabelas e os gatilhos de imutabilidade."""
        con = dbm.conectar(app.config["DATABASE"])
        dbm.init_db(con)
        click.echo(f"Banco pronto em {app.config['DATABASE']}")

    @app.cli.command("create-admin")
    @click.option("--nome", prompt=True)
    @click.option("--email", prompt=True)
    @click.password_option()
    def create_admin(nome, email, password):
        """Cria um usuário administrador."""
        msg = security.senha_invalida(password)
        if msg:
            raise click.ClickException(msg)
        con = dbm.conectar(app.config["DATABASE"])
        dbm.init_db(con)
        con.execute("INSERT INTO users (nome,email,senha_hash,perfil,ativo,criado_em) VALUES (?,?,?,?,1,?)",
                    (nome.strip(), email.strip().lower(), security.hash_senha(password), "admin", dbm.agora_utc()))
        click.echo("Administrador criado.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Carrega dados fictícios (1 obra, 3 usuários, ~30 dias de RDOs) para demonstração."""
        con = dbm.conectar(app.config["DATABASE"])
        dbm.init_db(con)
        if con.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise click.ClickException("O banco já tem usuários. Use um banco vazio (apague a pasta instance/).")
        rnd = random.Random(42)
        agora = dbm.agora_utc()
        contas = [("Administrador Demo", "admin@demo.local", "Admin12345", "admin"),
                  ("Gestora Demo", "gestor@demo.local", "Gestor12345", "gestor"),
                  ("Engenheiro de Campo Demo", "campo@demo.local", "Campo12345", "campo")]
        for nome, email, senha, perfil in contas:
            con.execute("INSERT INTO users (nome,email,senha_hash,perfil,ativo,criado_em) VALUES (?,?,?,?,1,?)",
                        (nome, email, security.hash_senha(senha), perfil, agora))
        hoje = utils.hoje_local()
        oid = con.execute("INSERT INTO obras (nome,endereco,responsavel,data_inicio,data_prevista_fim,status,criado_em) VALUES (?,?,?,?,?,?,?)",
                          ("Residencial Exemplo – Bloco A", "Endereço fictício, 100", "Gestora Demo",
                           (hoje - timedelta(days=40)).isoformat(), (hoje + timedelta(days=200)).isoformat(),
                           "em_andamento", agora)).lastrowid
        for u in con.execute("SELECT id FROM users"):
            con.execute("INSERT INTO obra_usuarios (obra_id,user_id) VALUES (?,?)", (oid, u["id"]))
        equipes = [("Pedreiro", "Alvenaria"), ("Servente", "Alvenaria"), ("Carpinteiro", "Fôrmas"), ("Armador", "Estrutura"),
                   ("Eletricista", "Instalações"), ("Encanador", "Instalações"), ("Pintor", "Acabamento"), ("Servente", "Estrutura")]
        fids = []
        for i, (funcao, equipe) in enumerate(equipes, 1):
            fids.append(con.execute("INSERT INTO funcionarios (obra_id,nome,funcao,equipe) VALUES (?,?,?,?)",
                                    (oid, f"Funcionário {i:02d}", funcao, equipe)).lastrowid)
        autor = con.execute("SELECT * FROM users WHERE email='campo@demo.local'").fetchone()
        servicos = [("Alvenaria de vedação", "Pavimento 2"), ("Concretagem de laje", "Pavimento 3"), ("Armação de pilares", "Pavimento 3"),
                    ("Instalações hidráulicas", "Pavimento 1"), ("Reboco interno", "Pavimento 1"), ("Montagem de fôrmas", "Pavimento 3")]
        equip = ["Betoneira", "Guincho de obra", "Serra circular", "Compactador"]
        upload = app.config["UPLOAD_DIR"]
        n = 0
        for delta in range(30, -1, -1):
            d = hoje - timedelta(days=delta)
            if d.weekday() == 6 or rnd.random() < 0.08:
                continue
            chuva = rnd.random() < 0.15
            clima = ("chuva_forte", "chuva_fraca") if chuva else rnd.choice([("ensolarado", "ensolarado"), ("ensolarado", "nublado"), ("nublado", "nublado")])
            base = rnd.randint(58, 72) if chuva or delta in (9, 10) else rnd.randint(78, 98)
            local = datetime.combine(d, time(17, 30), tzinfo=utils.tz()).astimezone(timezone.utc)
            fotos = []
            if rnd.random() < 0.7:
                for k in range(rnd.randint(1, 2)):
                    nome = uuid.uuid4().hex + ".png"
                    dados_png = _png(320, 200, (rnd.randint(90, 200), rnd.randint(90, 200), rnd.randint(90, 200)))
                    with open(os.path.join(upload, nome), "wb") as fh:
                        fh.write(dados_png)
                    fotos.append({"arquivo": nome, "nome_original": f"foto_{d.isoformat()}_{k + 1}.png", "sha256": sha256(dados_png).hexdigest(),
                                  "tamanho": len(dados_png), "legenda": rnd.choice(["Frente de serviço", "Detalhe da execução", "Estado do local"])})
            ocorr = []
            if rnd.random() < 0.28:
                tipo = rnd.choice(list(services.TIPOS_OCORRENCIA))
                ocorr.append({"tipo": "interferencia_climatica" if chuva else tipo,
                              "gravidade": rnd.choices(["baixa", "media", "alta"], [5, 4, 1])[0],
                              "descricao": "Ocorrência fictícia registrada para demonstração do sistema."})
            ok_loc = rnd.random() < 0.88
            dados = {
                "data_ref": d.isoformat(), "clima_manha": clima[0], "clima_tarde": clima[1],
                "condicao": "parcial" if chuva else "praticavel", "horas_improdutivas": float(rnd.randint(3, 6)) if chuva else float(rnd.choice([0, 0, 0, 1])),
                "efetivo_extra": rnd.randint(0, 3), "observacoes": "Registro fictício gerado por seed-demo.",
                "servicos": [{"descricao": s, "local": l, "atingimento": max(20, min(100, base + rnd.randint(-8, 8)))}
                             for s, l in rnd.sample(servicos, rnd.randint(2, 3))],
                "equipamentos": [{"nome": e, "horas": float(rnd.randint(2, 8)), "situacao": rnd.choice(["operando", "operando", "parado"])}
                                 for e in rnd.sample(equip, rnd.randint(1, 2))],
                "presencas": rnd.sample(fids, rnd.randint(5, len(fids))), "ocorrencias": ocorr,
                "lat": -9.3996 + rnd.uniform(-0.0004, 0.0004) if ok_loc else None,
                "lon": -38.2162 + rnd.uniform(-0.0004, 0.0004) if ok_loc else None,
                "precisao_m": round(rnd.uniform(4, 25), 1) if ok_loc else None,
                "loc_status": "ok" if ok_loc else "negada",
                "criado_em": local.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "form_aberto_em": (local - timedelta(minutes=9)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "tempo_preenchimento_s": rnd.randint(180, 540),
            }
            services.criar_rdo(con, oid, autor, dados, fotos, {"ip": "127.0.0.1", "user_agent": "seed-demo"})
            n += 1
        click.echo(f"{n} registros criados na obra de demonstração.")
        click.echo("Acessos de demonstração (troque ou apague antes de usar de verdade):")
        for _n, email, senha, perfil in contas:
            click.echo(f"  {perfil:7s} {email}  /  {senha}")
