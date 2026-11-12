-- Esquema do banco SQLite do Diário de Obras Digital.
-- Datas e horas de criação são gravadas em UTC (ISO 8601, sufixo Z) pelo servidor.

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nome TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  senha_hash TEXT NOT NULL,
  perfil TEXT NOT NULL CHECK (perfil IN ('admin','gestor','campo')),
  ativo INTEGER NOT NULL DEFAULT 1,
  criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS obras (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nome TEXT NOT NULL,
  endereco TEXT,
  responsavel TEXT,
  data_inicio TEXT NOT NULL,
  data_prevista_fim TEXT,
  status TEXT NOT NULL DEFAULT 'em_andamento' CHECK (status IN ('em_andamento','paralisada','concluida')),
  criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS obra_usuarios (
  obra_id INTEGER NOT NULL REFERENCES obras(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  PRIMARY KEY (obra_id, user_id)
);

CREATE TABLE IF NOT EXISTS funcionarios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  obra_id INTEGER NOT NULL REFERENCES obras(id),
  nome TEXT NOT NULL,
  funcao TEXT NOT NULL,
  equipe TEXT,
  ativo INTEGER NOT NULL DEFAULT 1
);

-- Registro Diário de Obra (RDO). Imutável após criado (ver gatilhos em db.py).
CREATE TABLE IF NOT EXISTS rdos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  obra_id INTEGER NOT NULL REFERENCES obras(id),
  data_ref TEXT NOT NULL,
  autor_id INTEGER NOT NULL REFERENCES users(id),
  autor_nome TEXT NOT NULL,
  criado_em TEXT NOT NULL,
  form_aberto_em TEXT,
  tempo_preenchimento_s INTEGER,
  clima_manha TEXT NOT NULL,
  clima_tarde TEXT NOT NULL,
  condicao TEXT NOT NULL,
  horas_improdutivas REAL NOT NULL DEFAULT 0,
  efetivo_extra INTEGER NOT NULL DEFAULT 0,
  observacoes TEXT,
  lat REAL,
  lon REAL,
  precisao_m REAL,
  loc_status TEXT NOT NULL,
  ip TEXT,
  user_agent TEXT,
  hash_anterior TEXT,
  hash TEXT NOT NULL,
  UNIQUE (obra_id, data_ref)
);

CREATE TABLE IF NOT EXISTS rdo_servicos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rdo_id INTEGER NOT NULL REFERENCES rdos(id),
  descricao TEXT NOT NULL,
  local TEXT,
  atingimento INTEGER NOT NULL CHECK (atingimento BETWEEN 0 AND 100)
);

CREATE TABLE IF NOT EXISTS rdo_equipamentos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rdo_id INTEGER NOT NULL REFERENCES rdos(id),
  nome TEXT NOT NULL,
  horas REAL NOT NULL,
  situacao TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rdo_presencas (
  rdo_id INTEGER NOT NULL REFERENCES rdos(id),
  funcionario_id INTEGER NOT NULL REFERENCES funcionarios(id),
  PRIMARY KEY (rdo_id, funcionario_id)
);

CREATE TABLE IF NOT EXISTS ocorrencias (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  obra_id INTEGER NOT NULL REFERENCES obras(id),
  rdo_id INTEGER NOT NULL REFERENCES rdos(id),
  tipo TEXT NOT NULL,
  gravidade TEXT NOT NULL CHECK (gravidade IN ('baixa','media','alta')),
  descricao TEXT NOT NULL,
  criado_em TEXT NOT NULL,
  autor_id INTEGER NOT NULL REFERENCES users(id),
  autor_nome TEXT NOT NULL
);

-- Histórico append-only: o status atual da ocorrência é o da última atualização.
CREATE TABLE IF NOT EXISTS ocorrencia_updates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ocorrencia_id INTEGER NOT NULL REFERENCES ocorrencias(id),
  autor_id INTEGER NOT NULL REFERENCES users(id),
  autor_nome TEXT NOT NULL,
  criado_em TEXT NOT NULL,
  texto TEXT NOT NULL,
  novo_status TEXT CHECK (novo_status IN ('aberta','em_tratamento','resolvida'))
);

CREATE TABLE IF NOT EXISTS fotos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rdo_id INTEGER NOT NULL REFERENCES rdos(id),
  arquivo TEXT NOT NULL UNIQUE,
  nome_original TEXT,
  sha256 TEXT NOT NULL,
  tamanho INTEGER NOT NULL,
  legenda TEXT,
  criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retificacoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rdo_id INTEGER NOT NULL REFERENCES rdos(id),
  autor_id INTEGER NOT NULL REFERENCES users(id),
  autor_nome TEXT NOT NULL,
  criado_em TEXT NOT NULL,
  texto TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  user_id INTEGER,
  user_nome TEXT,
  acao TEXT NOT NULL,
  detalhe TEXT,
  ip TEXT
);

CREATE TABLE IF NOT EXISTS login_falhas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT,
  ip TEXT,
  ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_rdos_obra_data ON rdos(obra_id, data_ref);
CREATE INDEX IF NOT EXISTS ix_serv_rdo ON rdo_servicos(rdo_id);
CREATE INDEX IF NOT EXISTS ix_ocorr_obra ON ocorrencias(obra_id);
CREATE INDEX IF NOT EXISTS ix_ocorr_rdo ON ocorrencias(rdo_id);
CREATE INDEX IF NOT EXISTS ix_fotos_rdo ON fotos(rdo_id);
CREATE INDEX IF NOT EXISTS ix_falhas_ts ON login_falhas(ts);
