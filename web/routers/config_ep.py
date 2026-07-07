from fastapi import APIRouter, Depends
from web.config import require_auth, get_config

router = APIRouter()

@router.get("/api/config")
def handle_get_config(user: str = Depends(require_auth)):
    cfg = get_config()["main"]

    return {
        "domain": cfg["domain"]
    }
