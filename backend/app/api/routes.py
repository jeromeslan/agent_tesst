"""Routes REST consommées par le dashboard React (aucune auth — PoC)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..db.database import get_session_factory

router = APIRouter(prefix="/api")


def _pipeline(request: Request):
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline non démarré.")
    return pipeline


# -- statut -----------------------------------------------------------------
@router.get("/status")
async def get_status(request: Request) -> dict:
    return await _pipeline(request).get_status()


# -- signaux ----------------------------------------------------------------
@router.get("/signals")
async def get_signals(request: Request) -> dict:
    states = await _pipeline(request).get_latest()
    return {"signals": states}


@router.get("/signals/history")
async def get_history(
    request: Request,
    pair: str = Query(..., description="Ex: BTC/USD"),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    rows = await _pipeline(request).get_history(pair, limit)
    return {"pair": pair, "history": rows}


@router.post("/signals/refresh")
async def refresh_now(request: Request) -> dict:
    """Déclenche un cycle d'analyse immédiat (pratique en démo)."""
    states = await _pipeline(request).run_cycle()
    return {"signals": states}


# -- configuration (mode + seuil) --------------------------------------------
class ModeUpdate(BaseModel):
    mode: Literal["FULL_AUTO", "HITM"]


class ThresholdUpdate(BaseModel):
    threshold: int = Field(ge=0, le=100)


@router.put("/config/mode")
async def set_mode(request: Request, body: ModeUpdate) -> dict:
    pipeline = _pipeline(request)
    mode = await pipeline.modes.set_mode(body.mode)
    return {"mode": mode}


@router.put("/config/threshold")
async def set_threshold(request: Request, body: ThresholdUpdate) -> dict:
    pipeline = _pipeline(request)
    threshold = await pipeline.modes.set_threshold(body.threshold)
    return {"threshold": threshold}


# -- ordres paper trading -----------------------------------------------------
@router.get("/orders")
async def list_orders(
    request: Request,
    status: str | None = Query(None, description="PENDING | FILLED | REJECTED"),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    if status is not None and status not in ("PENDING", "FILLED", "REJECTED"):
        raise HTTPException(status_code=400, detail=f"Statut inconnu : {status!r}")
    orders = await _pipeline(request).list_orders(status=status, limit=limit)
    return {"orders": orders}


@router.post("/orders/{order_id}/approve")
async def approve_order(request: Request, order_id: str) -> dict:
    pipeline = _pipeline(request)
    async with get_session_factory()() as session:
        order = await pipeline.executor.approve(session, order_id)
        if order is None:
            raise HTTPException(
                status_code=404, detail="Ordre introuvable ou déjà traité."
            )
        await session.commit()
        return {"id": order.id, "status": order.status}


@router.post("/orders/{order_id}/reject")
async def reject_order(request: Request, order_id: str) -> dict:
    pipeline = _pipeline(request)
    async with get_session_factory()() as session:
        order = await pipeline.executor.reject(session, order_id)
        if order is None:
            raise HTTPException(
                status_code=404, detail="Ordre introuvable ou déjà traité."
            )
        await session.commit()
        return {"id": order.id, "status": order.status}
