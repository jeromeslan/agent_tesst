# ⚡ Hybrid Algo-Trading PoC — Déterministe + LLM

Système de trading algorithmique hybride :

- **Ingestion Kraken** : bootstrap historique via REST (`/0/public/OHLC`) + écoute
  live des clôtures via **WebSocket public v2** (reconnect auto, backoff exponentiel).
- **Moteur déterministe** : RSI, Bandes de Bollinger, ADX/±DI, EMA 9/21, ATR et
  analyse du volume sur **M1 / M5 / M15** → `LONG | HOLD | SHORT` + confiance 0-100.
- **Agent LLM (appel RÉEL, jamais mocké)** : SDK `openai`, modèle `gpt-4o` par
  défaut, **Structured Outputs** (repli JSON Mode) → signal ajusté + confiance
  finale + justification.
- **Stockage TimescaleDB** : chaque cycle persisté en **Hypertable**
  (`analysis_cycles`, payload LLM brut en `JSONB`) + ordres (`paper_orders`).
- **Modes** : `FULL_AUTO` (exécution paper si score ≥ seuil) / `HITM`
  (validation humaine via API).
- **Exécution MOCKÉE (paper trading)** : seule partie simulée, succès enregistré en base.
- **Frontend React** : dashboard temps réel (polling 5 s), toggle de mode,
  boutons Approuver/Rejeter en HITM. Aucun graphique de prix (volontaire).

> **Précision arena.ai** : le LLM est appelé via le SDK OpenAI avec une
> `base_url` configurable. Il peut donc s'agir de **tout modèle du set
> arena.ai exposé via un endpoint compatible OpenAI**
> (GPT, Claude, Gemini, Grok, Qwen, Kimi…) — voir § Configuration LLM.

---

## Arborescence

```
.
├── docker-compose.yml          # db (TimescaleDB) + backend + frontend
├── .env.example                # variables d'environnement
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt        # fastapi, openai, sqlalchemy, asyncpg, numpy...
│   ├── app/
│   │   ├── main.py             # FastAPI : lifespan, CORS, REST + WS /ws/signals
│   │   ├── config.py           # pydantic-settings (env / .env)
│   │   ├── kraken/             # rest.py (bootstrap), websocket.py (live), store.py
│   │   ├── quant/              # indicators.py (RSI/BB/ADX/EMA/ATR), engine.py
│   │   ├── llm/                # agent.py (SDK openai RÉEL), prompts.py, schemas.py
│   │   ├── trading/            # modes.py (FULL_AUTO/HITM), executor.py (paper mock)
│   │   ├── services/           # pipeline.py (orchestrateur Kraken→Quant→LLM→DB→exec)
│   │   ├── api/                # routes.py (status, signaux, config, ordres)
│   │   └── db/                 # database.py, models.py (Hypertables + JSONB)
│   └── tests/                  # pytest : indicateurs + moteur
└── frontend/
    ├── Dockerfile + nginx.conf # build Vite servi par nginx (proxy /api)
    ├── package.json
    └── src/                    # App.jsx, api.js, components/
```

## Démarrage rapide (Docker — recommandé)

```bash
cp .env.example .env
# renseigner au minimum : LLM_API_KEY=<votre clé> (+ LLM_BASE_URL/LLM_MODEL si gateway arena.ai)

docker compose up --build
```

- Dashboard : **http://localhost:3000**
- API : **http://localhost:8000** — docs : http://localhost:8000/docs — health : `/health`
- TimescaleDB : `localhost:5432` (trader/trader_secret/trading)

## Démarrage local (sans Docker)

```bash
# Backend (fallback SQLite si DATABASE_URL=sqlite+aiosqlite:///./trading.db)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="sqlite+aiosqlite:///./trading.db" LLM_API_KEY="sk-..."
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend
cd frontend
npm install
npm run dev   # http://localhost:5173 (proxy /api -> :8000)
```

## Configuration LLM (set arena.ai)

| Variable | Défaut | Rôle |
|---|---|---|
| `LLM_ENABLED` | `true` | Active/coupe l'agent (repli déterministe si `false`) |
| `LLM_PROVIDER` | `openai` | Libellé informatif (affiché au dashboard) |
| `LLM_MODEL` | `gpt-4o` | Modèle appelé via le SDK |
| `LLM_API_KEY` | — | **Clé requise** (appel réel, non mocké) |
| `LLM_BASE_URL` | — | Endpoint compatible OpenAI (gateway arena.ai, OpenRouter, LiteLLM…). Vide = OpenAI direct |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` / `LLM_TEMPERATURE` | 30 / 2 / 0.1 | Robustesse |

Exemple gateway arena.ai (endpoint compatible OpenAI) :

```bash
LLM_PROVIDER=arena
LLM_MODEL=<modèle arena.ai, ex: gpt-4o>
LLM_API_KEY=<clé arena.ai>
LLM_BASE_URL=https://<votre-gateway-compatible-openai>/v1
```

Fiabilité : Structured Outputs strict → repli JSON Mode → extraction JSON
tolérante. Si le LLM reste injoignable, le pipeline **ne bloque jamais** :
verdict de repli calqué sur le déterministe (`fallback: true`, justification
explicite, confiance plafonnée à 50).

## API (extraits)

| Méthode | Route | Description |
|---|---|---|
| GET | `/health` | Santé + état WS Kraken |
| GET | `/api/status` | Mode, seuil, paires, LLM, dernier cycle |
| GET | `/api/signals` | Dernier état par paire (indicateurs M1/M5/M15, dét., LLM, volume) |
| POST | `/api/signals/refresh` | Déclenche un cycle immédiat |
| PUT | `/api/config/mode` | `{"mode": "FULL_AUTO" \| "HITM"}` |
| PUT | `/api/config/threshold` | `{"threshold": 0-100}` |
| GET | `/api/orders?status=PENDING` | Ordres paper (filtre optionnel) |
| POST | `/api/orders/{id}/approve` | Valider (HITM → FILLED simulé) |
| POST | `/api/orders/{id}/reject` | Rejeter (HITM) |
| WS | `/ws/signals` | Push JSON (statut + signaux + ordres PENDING) toutes les 5 s |

## Base de données

- `analysis_cycles(time, pair, timeframe, det_signal, det_score, llm_signal,
  llm_score, volume, indicators JSONB, llm_raw JSONB, ...)` — Hypertable.
- `paper_orders(time, pair, side, price, quantity, status, ..., llm_raw JSONB)` — Hypertable.
- Inserts **asynchrones** (SQLAlchemy `asyncpg`) à chaque cycle.
- Création des Hypertables **idempotente** au démarrage (`if_not_exists`).

## Tests

```bash
cd backend && python -m pytest tests/ -q
```

## Robustesse réseau

- WS Kraken : reconnexion infinie avec backoff exponentiel + jitter, ping/pong,
  callback isolé (une erreur n'interrompt jamais la boucle).
- REST : retries `tenacity` (5 tentatives, backoff exponentiel).
- Pipeline : un échec sur une paire n'interrompt pas le cycle ; la boucle
  d'analyse ne meurt jamais (try/except global + log).
- LLM : timeouts + retries SDK, puis repli déterministe tracé.

## Avertissement

PoC pédagogique — **paper trading uniquement**, aucun ordre réel n'est envoyé.
Pas d'authentification (à ajouter avant toute exposition publique).
