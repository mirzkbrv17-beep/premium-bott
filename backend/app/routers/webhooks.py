"""Provayder webhooklari: imzo tekshiriladi, summa/valyuta/order serverda solishtiriladi, idempotent qayta ishlanadi."""
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..errors import DomainError
from ..models import TopUp
from ..providers.base import PaymentEvent
from ..providers.impls import PROVIDERS, ClickProvider
from ..services import topup as topup_svc

router = APIRouter(prefix="/api/webhooks")


@router.post("/click")
async def click(request: Request):
    """Click Shop API: action=0 (prepare) va action=1 (complete). Sandbox'da sinab ko'rilishi shart."""
    p = ClickProvider()
    if not p.configured():
        return JSONResponse({"error": -9, "error_note": "not_configured"}, status_code=503)
    form = {k: str(v) for k, v in (await request.form()).items()}
    base = {"click_trans_id": form.get("click_trans_id"), "merchant_trans_id": form.get("merchant_trans_id")}
    if form.get("service_id") != settings.click_service_id or not p.verify_form(form):
        return {**base, "error": -1, "error_note": "SIGN CHECK FAILED"}
    action = form.get("action")
    async with SessionLocal() as s:
        try:
            t = (await s.execute(select(TopUp).where(TopUp.public_id == form.get("merchant_trans_id")).with_for_update())).scalar_one_or_none()
            if t is None:
                return {**base, "error": -5, "error_note": "Order not found"}
            if t.provider != "click" or int(float(form.get("amount", "0"))) != t.uzs_amount:
                return {**base, "error": -2, "error_note": "Incorrect amount"}
            if t.status == "success":
                return {**base, "error": -4, "error_note": "Already paid"}
            if t.status not in ("pending",):
                return {**base, "error": -9, "error_note": "Transaction cancelled"}
            if action == "0":
                return {**base, "merchant_prepare_id": t.id, "error": 0, "error_note": "Success"}
            if action == "1":
                failed = int(form.get("error", "0")) < 0
                ev = PaymentEvent(event_id=f"click:{form.get('click_trans_id')}", topup_public_id=t.public_id,
                                  status="failed" if failed else "success", paid_amount=t.uzs_amount, external_id=form.get("click_trans_id"))
                await topup_svc.process_event(s, "click", ev)
                await s.commit()
                return {**base, "merchant_confirm_id": t.id, "error": 0 if not failed else -9, "error_note": "Success" if not failed else "Cancelled"}
            return {**base, "error": -3, "error_note": "Action not found"}
        except DomainError as e:
            await s.rollback()
            return {**base, "error": -8, "error_note": e.message}


@router.post("/{provider}")
async def generic(provider: str, request: Request):
    impl = PROVIDERS.get(provider)
    if impl is None or impl.kind != "external" or provider == "click" or not impl.configured():
        return JSONResponse({"error": "unknown_provider"}, status_code=404)
    body = await request.body()
    if not impl.verify_webhook({k.lower(): v for k, v in request.headers.items()}, body):
        return JSONResponse({"error": "bad_signature"}, status_code=401)  # imzo noto'g'ri -> hech narsa o'zgarmaydi
    try:
        ev = impl.parse_webhook(body)
    except (KeyError, ValueError, json.JSONDecodeError):
        return JSONResponse({"error": "bad_payload"}, status_code=400)
    async with SessionLocal() as s:
        try:
            res = await topup_svc.process_event(s, provider, ev)
            await s.commit()
        except DomainError as e:
            await s.rollback()
            return JSONResponse({"error": e.code, "message": e.message}, status_code=e.status)
    return {"ok": True, "result": res}
