from minecraft.get_hypixel import get_hypixel_stats
from minecraft.get_donut import get_donut_stats

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from database.database import DBConnection
from web.config import require_auth
from datetime import datetime
import json
import time

router = APIRouter()


class BulkDeleteRequest(BaseModel):
    account_ids: list[str] = Field(default_factory=list)


@router.get("/api/accounts")
def accounts(user: str = Depends(require_auth)):
    with DBConnection() as db:
        return db.get_all_secured_accounts()


@router.get("/api/accounts/autobuy")
def autobuy_accounts(user: str = Depends(require_auth)):
    """Accounts sold through the Discord autobuy panel."""
    with DBConnection() as db:
        return db.get_autobuy_secured_accounts()


@router.get("/api/accounts/{account_id}")
def account_detail(account_id: str, user: str = Depends(require_auth)):
    with DBConnection() as db:
        row = db.get_secured_account(account_id)
        if not row:
            raise HTTPException(404, detail="Account not found.")
        
        return row

@router.post("/api/accounts/bulk-delete")
def bulk_delete_accounts(body: BulkDeleteRequest, user: str = Depends(require_auth)):
    ids = [aid.strip() for aid in body.account_ids if aid and aid.strip()]
    if not ids:
        raise HTTPException(400, detail="No account IDs provided.")
    with DBConnection() as db:
        deleted = db.delete_secured_accounts(ids)
        return {"ok": True, "deleted": deleted}

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
