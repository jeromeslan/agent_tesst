"""Point d'entrée FastAPI : lifespan, CORS, routes, WebSocket temps réel."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .config import get_settings
from .db.database import close_db, init_db
from .services.pipeline import TradingPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.getLogger().setLevel(settings.log_level.upper())
    logger.info("Initialisation base de données...")
    await init_db()
    pipeline = TradingPipeline()
    app.state.pipeline = pipeline
    logger.info("Démarrage pipeline de trading...")
    await pipeline.start()
    yield
    logger.info("Arrêt pipeline...")
    await pipeline.stop()
    await close_db()


app = FastAPI(title="Hybrid Algo-Trading PoC", version="0.1.0", lifespan=lifespan)

# PoC sans auth : CORS ouvert pour le dashboard React.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health() -> dict:
    pipeline: TradingPipeline | None = getattr(app.state, "pipeline", None)
    return {
        "status": "ok",
        "ws_connected": pipeline.ws.is_connected if pipeline else False,
    }


@app.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket) -> None:
    """Push temps réel de l'état des signaux (toutes les 5s)."""
    await websocket.accept()
    pipeline: TradingPipeline | None = getattr(websocket.app.state, "pipeline", None)
    try:
        while True:
            if pipeline is not None:
                payload = {
                    "type": "signals",
                    "status": await pipeline.get_status(),
                    "signals": await pipeline.get_latest(),
                    "pending_orders": await pipeline.list_orders(status="PENDING", limit=20),
                }
                await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("Erreur WebSocket /ws/signals")
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
