# Feature B: Canvas Mini App (Telegram Web App) — Design

**Data:** 2026-07-01
**Contexto:** O canvas hoje só existe como texto no `/status`. Esta feature entrega uma visualização rica: um **Telegram Mini App** que abre dentro do próprio Telegram mostrando a grade clássica do Business Model Canvas, com drill-down nos itens estratégicos que sustentam cada bloco. Read-only por decisão: quem muda o canvas é a conversa, não a UI.

---

## 1. Proposta

- Comando **`/canvas`** no grupo → bot responde com um botão inline `web_app` ("📋 Abrir Canvas").
- O botão abre o Mini App **dentro do Telegram** (mobile e desktop), servido por HTTPS.
- A página mostra a grade canônica de 9 blocos do BMC; tocar num bloco abre um painel com os itens estratégicos vinculados (conteúdo, tipo, status).
- Tema claro/escuro herdado do Telegram (`themeParams`).

## 2. Arquitetura

```
Telegram ─ /canvas ─► botão web_app (URL = WEBAPP_URL + ?chat_id=<id>)
                            │ Telegram abre a página e injeta initData assinado
                            ▼
   túnel HTTPS ──► FastAPI (processo separado: python -m concierge.webapp)
   (cloudflared/       ├─ GET  /              → static/index.html (página única)
    ngrok)             └─ POST /api/canvas    → valida initData (HMAC) → JSON
                                    │
                                    ▼
                        SQLite em modo WAL (leitura)
                        o MESMO concierge.db que o bot escreve
```

**Decisões estruturais:**
- **Processo separado** do bot (não compartilham event loop). O bot escreve no SQLite; o webapp só lê. `PRAGMA journal_mode=WAL` habilitado no `init_schema` para leitura concorrente segura.
- **Config por env:** `WEBAPP_URL` (URL HTTPS pública do túnel ou host), `WEBAPP_PORT` (default 8080). O design é agnóstico a túnel vs. nuvem — só precisa da URL.
- **Frontend sem framework:** um único `static/index.html` (HTML/CSS/JS puro + script oficial `telegram-web-app.js`), no espírito autocontido do `slides.html`.

## 3. Componentes

### 3.1 Novo pacote `src/concierge/webapp/`

- **`server.py`** — app FastAPI:
  - `GET /` → serve `static/index.html`.
  - `POST /api/canvas` — body: `{init_data: str, chat_id: int}`. Fluxo: validar `init_data` (HMAC, §4) → resolver projeto por `chat_id` (`storage.get_project`) → montar payload → JSON. 401 se initData inválido; 404 se projeto inexistente.
  - `create_app(settings) -> FastAPI` (factory, testável com TestClient) e `main()` que roda uvicorn.
- **`auth.py`** — `validate_init_data(init_data: str, bot_token: str) -> bool`: implementa a validação oficial do Telegram (secret key = HMAC-SHA256("WebAppData", bot_token); hash dos campos ordenados; comparação constante-tempo). Rejeita initData com `auth_date` mais velho que 1 hora.
- **`static/index.html`** — página única:
  - grade 9 blocos no layout canônico do BMC (CSS grid: parcerias | atividades+recursos | proposta de valor | relacionamento+canais | segmentos; custos e receitas na base)
  - carrega `telegram-web-app.js`, envia `Telegram.WebApp.initData` + `chat_id` (da query string) ao `/api/canvas`
  - tocar num bloco → painel inferior (bottom sheet) com itens: conteúdo, chip de status (🟢 validated, 🔵 active), tipo
  - aplica `Telegram.WebApp.themeParams` como variáveis CSS
  - estados: carregando, canvas vazio ("ainda em construção — continue a conversa"), erro de rede

### 3.2 Payload do `/api/canvas`

```json
{
  "project": {"name": "...", "updated_at": 1750000000},
  "blocks": [
    {"block_name": "customer_segments", "content": "...", "item_ids": [3, 7]}
  ],
  "items": [
    {"id": 3, "type": "decision", "content": "...", "status": "validated"}
  ]
}
```

`blocks` vem de `canvas_blocks` (com `source_items` decodificado); `items` são os `strategic_items` em status `active`/`validated` do projeto. `updated_at` = maior `updated_at` dos blocos.

### 3.3 Mudanças em módulos existentes

- **`bot.py`**: handler `/canvas` → responde com `InlineKeyboardButton(text="📋 Abrir Canvas", web_app=WebAppInfo(url=f"{settings.webapp_url}/?chat_id={chat_id}"))`. Se `WEBAPP_URL` vazio → responde orientando configurar. Exige `/start`.
- **`config.py`**: `webapp_url: str = ""` (env `WEBAPP_URL`), `webapp_port: int = 8080` (env `WEBAPP_PORT`).
- **`storage.py`**: `init_schema` passa a executar `PRAGMA journal_mode=WAL`. Método novo `get_project_name(project_id) -> str`.

## 4. Segurança

- **Toda** resposta de dados exige `init_data` válido: HMAC verificado com o token do bot prova que a requisição veio de um Mini App aberto pelo Telegram. Sem validação → 401.
- `auth_date` limitado a 1h (evita replay de initData antigo).
- O servidor só lê o banco; nenhuma rota de escrita existe.
- O `chat_id` vem da URL do botão (gerada pelo bot no próprio grupo), e os dados servidos são os desse projeto. Nota consciente de MVP: um usuário de outro chat com initData válido poderia trocar o `chat_id` manualmente; a verificação de *membership* no chat fica como item de roadmap (exigiria chamada à Bot API por requisição).

## 5. Tratamento de erros

- Túnel/servidor fora do ar → o Telegram mostra erro nativo ao abrir o botão (nada a fazer no bot).
- initData inválido/expirado → 401 com corpo `{"error": "unauthorized"}`; a página mostra "abra pelo botão no Telegram".
- Projeto sem canvas → 200 com `blocks: []`; página mostra o estado vazio.
- Banco bloqueado momentaneamente → retry único na leitura; depois 503.

## 6. Testes

- `auth.py`: vetores de initData construídos no teste (assinar com token fake e validar; alterar um campo → rejeita; `auth_date` velho → rejeita).
- `/api/canvas` com TestClient + banco em memória: 401 sem initData; 404 chat sem projeto; 200 com payload correto (blocos + itens vinculados).
- `create_app` smoke: `GET /` devolve HTML contendo a grade.
- Frontend: verificação estática (HTML contém os 9 block names e o script telegram-web-app.js) — interação manual na demo.

## 7. Roteiro de execução (demo)

```bash
# terminal 1 — bot (como hoje)
PYTHONPATH=src python -m concierge.main
# terminal 2 — webapp
PYTHONPATH=src python -m concierge.webapp
# terminal 3 — túnel
cloudflared tunnel --url http://localhost:8080   # copia a URL para WEBAPP_URL e reinicia o bot
```

## 8. Dependências novas

`fastapi`, `uvicorn` (pinadas, wheels Python 3.14).

## 9. Fora do escopo

- Edição pela UI (validar itens, editar blocos) — a conversa é a fonte de mudança.
- Verificação de membership do chat por requisição (roadmap, ver §4).
- Histórico/versões do canvas na UI.
- Deploy gerenciado (o design só exige uma URL HTTPS).
