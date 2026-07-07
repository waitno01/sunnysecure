from database.database import DBConnection
from fastapi import APIRouter, Depends
from web.config import require_auth

router = APIRouter()


@router.get("/api/stats")
def stats(user: str = Depends(require_auth)):
    with DBConnection() as db:
        return db.get_stats()

@router.get("/api/detailed-stats")
def detailed_stats(user: str = Depends(require_auth)):
    with DBConnection() as db:
        return db.get_detailed_stats()

@router.get("/api/chart")
def chart(user: str = Depends(require_auth)):
    with DBConnection() as db:
        return db.get_chart_data()
