from web.config import verify_password, verify_totp, issue_token, require_auth, get_config, COOKIE_NAME, COOKIE_SECURE, TOKEN_TTL_HOURS
from web.limiter import limiter
from web.models import LoginRequest, ChangePasswordRequest, Setup2FARequest
from fastapi import APIRouter, Depends, Request, Response, HTTPException
import json

router = APIRouter()


@router.post("/api/auth/login")
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest, response: Response):
    credentials = get_config()["main"]["web"]["credentials"]
    if body.username != credentials["username"] or not verify_password(body.password):
        raise HTTPException(401, detail="Invalid credentials.")

    if "totp_secret" in credentials and credentials["totp_secret"]:

        if not body.totp_code:
            return {"require_2fa": True}
        
        if not await verify_totp(body.totp_code):
            raise HTTPException(401, detail="Invalid 2FA code.")

    response.set_cookie(
        key=COOKIE_NAME,
        value=issue_token(),
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=TOKEN_TTL_HOURS * 3600,
        path="/",
    )

    return {"ok": True}


@router.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/api/me")
def me(user: str = Depends(require_auth)):
    config = get_config()["main"]
    
    return {
        "username": config["web"]["credentials"]["username"]
    }


@router.post("/api/auth/change-password")
async def change_password(body: ChangePasswordRequest, user: str = Depends(require_auth)):
    config = get_config()["main"]

    if not verify_password(body.current_password):
        raise HTTPException(400, detail="Current password is incorrect.")

    if len(body.new_password) < 6:
        raise HTTPException(400, detail="New password must be at least 6 characters.")

    creds = config["web"]["credentials"]
    if "totp_secret" in creds and creds["totp_secret"]:
        if not body.totp_code or not await verify_totp(body.totp_code):
            raise HTTPException(400, detail="Invalid 2FA code.")

    config["web"]["credentials"]["password"] = body.new_password
    with open("config/config.json", "w") as f:
        json.dump(config, f, indent=2)

    return {"ok": True}


@router.post("/api/auth/setup-2fa")
def setup_2fa(body: Setup2FARequest, user: str = Depends(require_auth)):
    if not body.secret.strip():
        raise HTTPException(400, detail="Secret cannot be empty.")

    config = get_config()["main"]
    config["web"]["credentials"]["totp_secret"] = body.secret.strip()
    with open("config/config.json", "w") as f:
        json.dump(config, f, indent=2)

    return {"ok": True}


@router.get("/api/auth/2fa-status")
def twofa_status(user: str = Depends(require_auth)):
    config = get_config()["main"]
    
    return {
        "configured": "totp_secret" in config["web"]["credentials"]
    }


@router.post("/api/auth/remove-2fa")
def remove_2fa(user: str = Depends(require_auth)):
    config = get_config()["main"]
    config["web"]["credentials"].pop("totp_secret", None)
    
    with open("config/config.json", "w") as f:
        json.dump(config, f, indent=2)

    return {"ok": True}
