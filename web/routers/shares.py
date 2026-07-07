from argon2.exceptions import VerifyMismatchError, InvalidHashError
from argon2 import PasswordHasher

from fastapi import APIRouter, Depends, HTTPException, Request
from database.database import DBConnection

from web.models import ShareLinkRequest
from web.config import require_auth
from web.limiter import limiter

import secrets, hashlib, hmac

router = APIRouter()
ph = PasswordHasher()

def verify_lpwd(stored: str, candidate: str) -> bool:
    try:

        ph.verify(stored, candidate)
        return True
    
    except VerifyMismatchError:
        return False
    except InvalidHashError:
        return hmac.compare_digest(
            hashlib.sha256(candidate.encode()).hexdigest(), stored
        )

@router.post("/api/accounts/{account_id}/share")
def create_share_link(account_id: str, body: ShareLinkRequest, user: str = Depends(require_auth)):
    with DBConnection() as db:
        if not db.is_valid_account_id(account_id):
            raise HTTPException(404, detail="Account not found.")
        
        link_id = secrets.token_hex(16)
        password = None
        if body.password:
            password = ph.hash(body.password)

        db.create_share_link(link_id, account_id, password)

    return {
        "link_id": link_id
    }

@router.get("/api/accounts/{account_id}/links")
def list_share_links(account_id: str, user: str = Depends(require_auth)):
    with DBConnection() as db:
        if not db.is_valid_account_id(account_id):
            raise HTTPException(404, detail="Account not found.")
        
        return db.get_shared_links_for_account(account_id)

@router.delete("/api/share/{link_id}")
def delete_share_link(link_id: str, user: str = Depends(require_auth)):
    with DBConnection() as db:
        link = db.get_share_link(link_id)
        if not link:
            raise HTTPException(404, detail="Link not found.")
        
        db.delete_share_link(link_id)

    return {"ok": True}


@router.post("/api/share/{link_id}/verify")
@limiter.limit("60/minute")
def verify_share_link(request: Request, link_id: str, body: ShareLinkRequest):
    with DBConnection() as db:
        link = db.get_share_link(link_id)
        if not link:
            raise HTTPException(404, detail="Link not found.")
        
        if link["password"]:
            if not body.password:
                raise HTTPException(401, detail="Password required.")
            
            if not verify_lpwd(link["password"], body.password):
                raise HTTPException(401, detail="Incorrect password.")
            
        db.increment_share_link_access(link_id)
        account = db.get_secured_account(link["account_id"])
        if not account:
            raise HTTPException(404, detail="Account not found.")

        return account
