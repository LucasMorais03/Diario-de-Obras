# Diário de Obras Digital

Sistema web de Relatório Diário de Obra (RDO) desenvolvido para o TCC *Desenvolvimento de um diário de obras digital para apoio na construção civil* (Bacharelado em Sistemas de Informação, UniRios).

Stack: **Python 3.10+**, **Flask**, **SQLite**, HTML5/CSS3 e JavaScript puro (sem CDN: funciona sem internet depois de instalado).

## O que o sistema faz

| Ideia do texto do TCC | Como está no sistema |
|---|---|
| Registro de atividades diárias (serviços, clima, efetivo, equipamentos, ocorrências) | Formulário "Novo registro" (`/obras/<id>/rdos/novo`) |
| Registro automático de data e hora (timestamp) | Gravado **pelo servidor** em UTC e exibido no fuso `America/Bahia`; o cliente não consegue informá-lo |
| Geolocalização | Capturada pelo navegador (latitude, longitude, precisão). Se for negada ou falhar, o registro é salvo **marcado** como "sem localização" |
| Identificação de autoria | Vem da sessão autenticada, nunca do formulário |
| Registro fotográfico organizado | Fotos por registro, com legenda, validação do arquivo e impressão digital SHA-256 |
| Controle de acessos | Perfis `admin`, `gestor` e `campo`; cada usuário só vê as obras a que foi vinculado |
| Controle de funcionários e equipes | Cadastro por obra e lista de presença no RDO |
| Consulta rápida de registros | Busca por texto, período, autor, "com ocorrência" e "sem localização" |
| Dashboards | Atingimento da meta diária, horas improdutivas por clima, efetivo, ocorrências, alertas de desvio e dias úteis sem registro |
| Relatórios gerenciais | Relatório do período (imprimir ou salvar em PDF pelo navegador) e exportação CSV |

### Mecanismos de integridade (acréscimos em relação ao texto)

1. **Registros imutáveis.** Gatilhos do SQLite recusam `UPDATE` e `DELETE` nas tabelas de registro e na trilha de auditoria. Correções são feitas por **retificação** (anexada, com autor e hora) e as ocorrências evoluem por **atualizações** (histórico somente de inclusão).
2. **Cadeia de hashes.** Cada RDO guarda o SHA-256 do seu conteúdo (incluindo serviços, efetivo, ocorrências e hashes das fotos) mais o hash do RDO anterior da obra. A tela *Integridade* recalcula tudo e confere os arquivos de foto.
3. **Trilha de auditoria** de logins, criações, retificações, exportações e verificações.
4. **Segurança de aplicação:** senhas com hash (scrypt/Werkzeug), bloqueio após 5 falhas em 10 minutos, token CSRF em todos os `POST`, cabeçalhos de segurança (CSP, `X-Frame-Options`, `nosniff`), cookies `HttpOnly` e `SameSite=Lax`, validação de imagens pelos primeiros bytes e controle de acesso por obra em cada rota (inclusive nas fotos).

**Limite honesto:** o hash e os gatilhos detectam e dificultam alterações, mas quem tem acesso total ao servidor pode refazer o banco inteiro. Para esse cenário, guarde cópias externas do último hash (por exemplo, no relatório impresso) e faça backup da pasta `instance/`.

### Dados para a avaliação comparativa (seção 3.9 do TCC)

O sistema já grava o que a avaliação futura vai precisar: `tempo_preenchimento_s` (da abertura do formulário ao envio), data do registro × data em que foi realmente registrado (atraso, mostrado como `+Nd`), completude por registro (serviços, efetivo, localização e foto) e o CSV exportável com tudo isso.

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export FLASK_APP=diario            # Windows (PowerShell): $env:FLASK_APP="diario"
flask create-admin                 # cria o primeiro administrador (pergunta nome, e-mail e senha)
flask run                          # http://127.0.0.1:5000
```

Para ver o sistema com dados fictícios (uma obra, três usuários e ~30 dias de registros):

```bash
flask seed-demo
```

Contas de demonstração (`admin@demo.local / Admin12345`, `gestor@demo.local / Gestor12345`, `campo@demo.local / Campo12345`). **Nunca use o seed em produção.** Para recomeçar do zero, apague a pasta `instance/`.

## Primeiros passos

1. Entre como administrador, abra **Usuários → Novo usuário** e crie os perfis.
2. Cadastre a obra (administrador ou gestor) e vincule os usuários na edição de cada usuário.
3. Cadastre os funcionários em **Equipe**.
4. A equipe de campo cria o registro do dia em **Novo registro**.

## Configuração (variáveis de ambiente)

| Variável | Padrão | Função |
|---|---|---|
| `DIARIO_SECRET_KEY` | gerada em `instance/secret_key` | Chave de sessão (defina em produção) |
| `DIARIO_COOKIE_SECURE` | `0` | Use `1` quando servir por HTTPS |
| `DIARIO_TZ` | `America/Bahia` | Fuso de exibição |
| `DIARIO_META_ATINGIMENTO` | `70` | Meta diária (%) abaixo da qual o dashboard alerta |
| `DIARIO_LIMITE_HORAS_CLIMA` | `2` | Horas improdutivas por dia a partir das quais há alerta |

## Em produção

- Sirva por **HTTPS**: os navegadores só liberam a geolocalização em HTTPS (ou `localhost`).
- Use um servidor WSGI (`pip install gunicorn` e `gunicorn wsgi:app`, ou `waitress` no Windows) atrás de um proxy reverso.
- Defina `DIARIO_SECRET_KEY` e `DIARIO_COOKIE_SECURE=1`.
- Faça backup periódico de `instance/diario.sqlite` e `instance/uploads/`.

## Testes

```bash
python -m unittest discover -s tests -t .
```

A suíte (18 testes) cobre login e bloqueio, CSRF, acesso por perfil e por obra, criação de RDO com foto, validações, autoria não forjável, imutabilidade no banco, detecção de adulteração (conteúdo, encadeamento e foto), retificações, ocorrências, busca, CSV, relatório e todas as telas com os dados de demonstração.

## Estrutura

```
diario/
  __init__.py   fábrica da aplicação, cabeçalhos de segurança, filtros
  schema.sql    esquema do banco
  db.py         conexão, transações e gatilhos de imutabilidade
  security.py   login, perfis, CSRF, auditoria, acesso por obra
  services.py   criação de RDO, cadeia de hashes, verificação e métricas
  charts.py     gráficos SVG gerados no servidor
  auth.py, admin.py, obras.py, rdos.py   rotas
  cli.py        init-db, create-admin, seed-demo
  templates/, static/
tests/test_sistema.py
wsgi.py
```

## Limitações conhecidas

- **Sem modo offline completo.** Há rascunho local (o navegador guarda o que foi digitado), mas o envio exige conexão. Fotos não entram no rascunho.
- Um RDO por obra por dia; informações adicionais entram por retificação.
- Sem exportação em PDF no servidor: use "Imprimir / PDF" do navegador.
- Sem campos personalizáveis, autenticação em dois fatores ou recuperação de senha por e-mail.
- SQLite atende bem equipes pequenas e médias; para muitos acessos simultâneos, considere PostgreSQL.
