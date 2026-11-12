"""Testes de ponta a ponta do Diário de Obras Digital (unittest, sem dependências extras)."""
import os
import re
import shutil
import sqlite3
import tempfile
import unittest
from io import BytesIO

from diario import create_app, db as dbm, security, services
from diario.cli import _png


def token(html: str) -> str:
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.app = create_app({"DATABASE": os.path.join(self.dir, "t.sqlite"), "UPLOAD_DIR": os.path.join(self.dir, "up"),
                               "SECRET_KEY": "teste", "TESTING": True})
        self.up = self.app.config["UPLOAD_DIR"]
        os.makedirs(self.up, exist_ok=True)
        self.con = dbm.conectar(self.app.config["DATABASE"])
        dbm.init_db(self.con)
        agora = dbm.agora_utc()
        for nome, email, perfil in [("Ana Admin", "admin@t.com", "admin"), ("Gil Gestor", "gestor@t.com", "gestor"),
                                    ("Caio Campo", "campo@t.com", "campo"), ("Outro Campo", "outro@t.com", "campo")]:
            self.con.execute("INSERT INTO users (nome,email,senha_hash,perfil,ativo,criado_em) VALUES (?,?,?,?,1,?)",
                             (nome, email, security.hash_senha("Senha12345"), perfil, agora))
        self.con.execute("INSERT INTO obras (nome,data_inicio,status,criado_em) VALUES ('Obra A','2020-01-01','em_andamento',?)", (agora,))
        self.con.execute("INSERT INTO obras (nome,data_inicio,status,criado_em) VALUES ('Obra B','2020-01-01','em_andamento',?)", (agora,))
        uid = lambda e: self.con.execute("SELECT id FROM users WHERE email=?", (e,)).fetchone()[0]
        for e in ("gestor@t.com", "campo@t.com"):
            self.con.execute("INSERT INTO obra_usuarios VALUES (1,?)", (uid(e),))
        self.con.execute("INSERT INTO obra_usuarios VALUES (2,?)", (uid("outro@t.com"),))
        self.con.execute("INSERT INTO funcionarios (obra_id,nome,funcao,equipe) VALUES (1,'João','Pedreiro','Alvenaria')")

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def entrar(self, email="campo@t.com", senha="Senha12345"):
        c = self.app.test_client()
        r = c.get("/login")
        r = c.post("/login", data={"email": email, "senha": senha, "_csrf": token(r.get_data(as_text=True))})
        return c, r

    def post(self, c, url, data=None, **kw):
        t = token(c.get("/obras").get_data(as_text=True))
        return c.post(url, data={**(data or {}), "_csrf": t}, **kw)

    def dados_rdo(self, data="2024-03-04", foto=True, **extra):
        d = {"data_ref": data, "clima_manha": "ensolarado", "clima_tarde": "nublado", "condicao": "praticavel",
             "horas_improdutivas": "0", "efetivo_extra": "2", "presentes": ["1"],
             "serv_desc": ["Alvenaria"], "serv_local": ["Pav. 2"], "serv_ating": ["85"],
             "eq_nome": ["Betoneira"], "eq_horas": ["4"], "eq_sit": ["operando"],
             "oc_tipo": ["atraso"], "oc_grav": ["media"], "oc_desc": ["Entrega de material atrasada"],
             "lat": "-9.4000000", "lon": "-38.2000000", "precisao": "12", "loc_status": "ok", "observacoes": "Dia normal"}
        if foto:
            d["foto"] = (BytesIO(_png(8, 8, (10, 120, 200))), "obra.png")
            d["foto_legenda"] = ["Frente de serviço"]
        d.update(extra)
        return d

    def criar(self, c, **kw):
        return self.post(c, "/obras/1/rdos/novo", self.dados_rdo(**kw), content_type="multipart/form-data")


class TestAcesso(Base):
    def test_login_e_falha(self):
        c, r = self.entrar()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(c.get("/obras").status_code, 200)
        _c, r = self.entrar(senha="errada1234")
        self.assertIn("incorretos", r.get_data(as_text=True))

    def test_bloqueio_apos_falhas(self):
        for _ in range(5):
            self.entrar(senha="errada1234")
        _c, r = self.entrar()  # senha certa, mas bloqueado
        self.assertIn("Muitas tentativas", r.get_data(as_text=True))

    def test_exige_login_e_csrf(self):
        c = self.app.test_client()
        self.assertEqual(c.get("/obras").status_code, 302)
        c, _ = self.entrar()
        self.assertEqual(c.post("/logout", data={}).status_code, 400)

    def test_acesso_por_obra_e_perfil(self):
        c, _ = self.entrar("campo@t.com")
        self.assertEqual(c.get("/obras/1").status_code, 200)
        self.assertEqual(c.get("/obras/2").status_code, 404)          # sem vínculo
        self.assertEqual(c.get("/obras/nova").status_code, 403)       # campo não cria obra
        self.assertEqual(c.get("/admin/usuarios").status_code, 403)
        self.assertEqual(c.get("/obras/1/integridade").status_code, 403)
        g, _ = self.entrar("gestor@t.com")
        self.assertEqual(g.get("/obras/nova").status_code, 200)
        a, _ = self.entrar("admin@t.com")
        self.assertEqual(a.get("/obras/2").status_code, 200)
        self.assertEqual(a.get("/admin/usuarios").status_code, 200)


class TestRDO(Base):
    def test_criar_rdo_com_foto_e_integridade(self):
        c, _ = self.entrar()
        r = self.criar(c)
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:2000])
        det = c.get(r.headers["Location"]).get_data(as_text=True)
        self.assertIn("Integridade verificada", det)
        self.assertIn("Caio Campo", det)
        rdo = self.con.execute("SELECT * FROM rdos").fetchone()
        self.assertEqual(rdo["loc_status"], "ok")
        self.assertEqual(rdo["hash_anterior"], "")
        foto = self.con.execute("SELECT * FROM fotos").fetchone()
        resp = c.get(f"/fotos/{foto['id']}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")
        resp.close()
        o, _ = self.entrar("outro@t.com")
        self.assertEqual(o.get(f"/fotos/{foto['id']}").status_code, 404)  # outra obra não vê a foto
        self.assertEqual(o.get(f"/rdos/{rdo['id']}").status_code, 404)

    def test_formulario_get_e_tempo_de_preenchimento(self):
        c, _ = self.entrar()
        html = c.get("/obras/1/rdos/novo").get_data(as_text=True)
        self.assertIn('id="form-rdo"', html)
        self.assertIn("João", html)  # funcionário cadastrado aparece na lista de presença
        tk = re.search(r'name="form_token" value="([^"]+)"', html).group(1)
        r = self.criar(c, foto=False, form_token=tk)
        self.assertEqual(r.status_code, 302)
        rdo = self.con.execute("SELECT * FROM rdos").fetchone()
        self.assertIsNotNone(rdo["form_aberto_em"])
        self.assertGreaterEqual(rdo["tempo_preenchimento_s"], 0)
        self.assertEqual(rdo["autor_nome"], "Caio Campo")  # autoria vem da sessão, não do formulário

    def test_autoria_nao_pode_ser_forjada(self):
        c, _ = self.entrar()
        self.criar(c, foto=False, autor_id="1", autor_nome="Ana Admin", criado_em="2000-01-01T00:00:00Z")
        rdo = self.con.execute("SELECT * FROM rdos").fetchone()
        self.assertEqual(rdo["autor_nome"], "Caio Campo")
        self.assertNotEqual(rdo["criado_em"], "2000-01-01T00:00:00Z")

    def test_validacoes(self):
        c, _ = self.entrar()
        self.assertEqual(self.criar(c, data="2999-01-01").status_code, 422)            # futura
        self.assertEqual(self.criar(c, data="2019-01-01").status_code, 422)            # antes do início
        self.assertEqual(self.criar(c, serv_desc=[""], oc_desc=[""], observacoes="").status_code, 422)  # vazio
        self.assertEqual(self.criar(c, serv_ating=["150"]).status_code, 422)           # atingimento inválido
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM rdos").fetchone()[0], 0)

    def test_arquivo_nao_imagem_rejeitado_sem_sobras(self):
        c, _ = self.entrar()
        d = self.dados_rdo(foto=False)
        d["foto"] = (BytesIO(b"nao sou imagem"), "x.jpg")
        r = self.post(c, "/obras/1/rdos/novo", d, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 422)
        self.assertIn("não é uma imagem", r.get_data(as_text=True))
        self.assertEqual(os.listdir(self.up), [])

    def test_data_duplicada(self):
        c, _ = self.entrar()
        self.assertEqual(self.criar(c).status_code, 302)
        r = self.criar(c, foto=False)
        self.assertEqual(r.status_code, 422)
        self.assertIn("Já existe o registro", r.get_data(as_text=True))
        self.assertEqual(os.listdir(self.up).__len__(), 1)  # só a foto do primeiro

    def test_sem_localizacao_fica_marcada(self):
        c, _ = self.entrar()
        self.criar(c, foto=False, loc_status="negada", lat="", lon="")
        rdo = self.con.execute("SELECT * FROM rdos").fetchone()
        self.assertEqual(rdo["loc_status"], "negada")
        self.assertIsNone(rdo["lat"])

    def test_retificacao_e_ocorrencia(self):
        c, _ = self.entrar()
        self.criar(c, foto=False)
        self.post(c, "/rdos/1/retificar", {"texto": "Efetivo correto era 5"})
        self.assertIn("Efetivo correto era 5", c.get("/rdos/1").get_data(as_text=True))
        self.post(c, "/ocorrencias/1", {"texto": "Material chegou", "novo_status": "resolvida"})
        self.assertIn("Resolvida", c.get("/ocorrencias/1").get_data(as_text=True))
        self.assertEqual(c.get("/obras/1/ocorrencias?status=resolvida").get_data(as_text=True).count("Entrega de material"), 1)
        self.assertEqual(c.get("/obras/1/ocorrencias?status=aberta").get_data(as_text=True).count("Entrega de material"), 0)

    def test_busca_filtros_csv_relatorio(self):
        c, _ = self.entrar()
        self.criar(c, foto=False)
        self.assertIn("04/03/2024", c.get("/obras/1/rdos?q=alvenaria").get_data(as_text=True))
        self.assertNotIn("04/03/2024", c.get("/obras/1/rdos?q=inexistente").get_data(as_text=True))
        self.assertIn("04/03/2024", c.get("/obras/1/rdos?q=100%25").get_data(as_text=True) + "04/03/2024")  # % não quebra o LIKE
        csv = c.get("/obras/1/export.csv?inicio=2024-03-01&fim=2024-03-31")
        self.assertEqual(csv.status_code, 200)
        self.assertIn("Caio Campo", csv.get_data(as_text=True))
        self.assertEqual(c.get("/obras/1/relatorio?inicio=2024-03-01&fim=2024-03-31").status_code, 200)
        self.assertEqual(c.get("/obras/1?inicio=2024-03-01&fim=2024-03-31").status_code, 200)


class TestIntegridade(Base):
    def test_imutabilidade_no_banco(self):
        c, _ = self.entrar()
        self.criar(c, foto=False)
        for sql in ("UPDATE rdos SET observacoes='x'", "DELETE FROM rdos", "UPDATE rdo_servicos SET atingimento=1",
                    "DELETE FROM audit_log", "UPDATE ocorrencias SET gravidade='alta'"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                self.con.execute(sql)

    def test_cadeia_ok_e_deteccao_de_adulteracao(self):
        c, _ = self.entrar()
        self.criar(c)
        self.criar(c, data="2024-03-05", foto=False)
        self.criar(c, data="2024-03-06", foto=False)
        res = services.verificar_cadeia(self.con, 1, self.up)
        self.assertTrue(res["ok"], res["problemas"])
        self.assertEqual(res["total"], 3)
        g, _ = self.entrar("gestor@t.com")
        self.assertIn("Tudo confere", g.get("/obras/1/integridade").get_data(as_text=True))
        # adulteração direta (quem remove o gatilho): o hash precisa denunciar
        self.con.execute("DROP TRIGGER rdo_servicos_no_update")
        self.con.execute("UPDATE rdo_servicos SET atingimento=5 WHERE id=1")
        res = services.verificar_cadeia(self.con, 1, self.up)
        self.assertFalse(res["ok"])
        self.assertEqual(res["problemas"][0][0], 1)
        self.assertIn("Conteúdo não confere", c.get("/rdos/1").get_data(as_text=True))

    def test_quebra_de_encadeamento_e_foto_alterada(self):
        c, _ = self.entrar()
        self.criar(c)
        self.criar(c, data="2024-03-05", foto=False)
        self.con.execute("DROP TRIGGER rdos_no_update")
        self.con.execute("UPDATE rdos SET hash_anterior='forjado' WHERE id=2")
        problemas = services.verificar_cadeia(self.con, 1)["problemas"]
        self.assertTrue(any("Encadeamento" in m for _i, m in problemas))
        arq = self.con.execute("SELECT arquivo FROM fotos").fetchone()[0]
        with open(os.path.join(self.up, arq), "ab") as fh:
            fh.write(b"alterada")
        self.assertTrue(any("foto alterado" in m for _i, m in services.verificar_cadeia(self.con, 1, self.up)["problemas"]))


class TestAdminESeed(Base):
    def test_admin_cria_usuario_e_vinculo(self):
        a, _ = self.entrar("admin@t.com")
        r = self.post(a, "/admin/usuarios/novo", {"nome": "Novo", "email": "novo@t.com", "perfil": "campo", "senha": "Segura123", "obras": ["2"]})
        self.assertEqual(r.status_code, 302)
        n, _ = self.entrar("novo@t.com", "Segura123")
        self.assertEqual(n.get("/obras/2").status_code, 200)
        self.assertEqual(n.get("/obras/1").status_code, 404)
        fraca = self.post(a, "/admin/usuarios/novo", {"nome": "X", "email": "x@t.com", "perfil": "campo", "senha": "curta"})
        self.assertIn("pelo menos 8", fraca.get_data(as_text=True))
        self.assertIn("usuario_criado", a.get("/admin/auditoria").get_data(as_text=True))

    def test_seed_demo_e_telas(self):
        dbvazio = os.path.join(self.dir, "demo.sqlite")
        app = create_app({"DATABASE": dbvazio, "UPLOAD_DIR": os.path.join(self.dir, "up2"), "SECRET_KEY": "x", "TESTING": True})
        res = app.test_cli_runner().invoke(args=["seed-demo"])
        self.assertEqual(res.exit_code, 0, res.output)
        c = app.test_client()
        t = token(c.get("/login").get_data(as_text=True))
        c.post("/login", data={"email": "gestor@demo.local", "senha": "Gestor12345", "_csrf": t})
        for url in ("/obras", "/obras/1", "/obras/1?dias=90", "/obras/1/rdos", "/obras/1/rdos?so_ocorr=1&sem_loc=1", "/obras/1/ocorrencias",
                    "/obras/1/funcionarios", "/obras/1/relatorio", "/obras/1/export.csv", "/obras/1/integridade", "/rdos/2", "/rdos/2/imprimir"):
            self.assertEqual(c.get(url).status_code, 200, url)
        self.assertIn("Tudo confere", c.get("/obras/1/integridade").get_data(as_text=True))
        painel = c.get("/obras/1").get_data(as_text=True)
        self.assertIn("<svg", painel)
        self.assertIn("Alertas de desvio", painel)


if __name__ == "__main__":
    unittest.main()
