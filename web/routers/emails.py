from database.database import DBConnection
from web.models import EmailCreateRequest
from fastapi import APIRouter, Depends
from web.config import require_auth, get_config

router = APIRouter()

@router.get("/api/emails")
def list_emails(user: str = Depends(require_auth)):
    with DBConnection() as db:

        rows = db.get_security_emails()
        result = []

        for (email,) in rows:

            inbox_rows = db.get_emails(email)
            result.append({
                "email": email,
                "inbox_count": len(inbox_rows),
                "inbox": [{
                    "id": r[0],
                    "to_address": r[1],
                    "from_address": r[2],
                    "subject": r[3],
                    "body": r[4],
                    "received_at": r[5],
                } for r in inbox_rows],
            })

        return result

@router.post("/api/emails")
def create_email(body: EmailCreateRequest, user: str = Depends(require_auth)):
    email = body.email
    
    if "@" not in email:
        cfg = get_config()["main"]
        domain = cfg["domain"]
        email = f"{email}@{domain}"

    with DBConnection() as db:
        db.add_security_email(email, "")

    return {"ok": True}

@router.delete("/api/emails")
def delete_emails(email: str, user: str = Depends(require_auth)):
    with DBConnection() as db:
        db.remove_security_email(email)

    return {"ok": True}
