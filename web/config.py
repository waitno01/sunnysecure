import hmac, json, os, secrets
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException, Request
from shared.gen_totp import totp
import jwt

ALGO = "HS256"
TOKEN_TTL_HOURS = 8
COOKIE_NAME = "session"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"

_jwt_secret_cache = None

def get_config():
    config = json.load(open("config/config.json"))
    bot_config = json.load(open("config/bot.json"))
    return {"main": config, "web": bot_config}

def get_jwt_secret() -> str:
    global _jwt_secret_cache
    if _jwt_secret_cache:
        return _jwt_secret_cache

    config = json.load(open("config/config.json"))
    web_cfg = config.setdefault("web", {})
    creds = web_cfg.setdefault("credentials", {})

    secret = creds.get("jwt_secret")
    if not secret:
        secret = secrets.token_hex(32)
        creds["jwt_secret"] = secret
        with open("config/config.json", "w") as f:
            json.dump(config, f, indent=2)

    _jwt_secret_cache = secret
    return secret

def verify_password(password: str) -> bool:
    creds = get_config()["main"]["web"]["credentials"]
    return hmac.compare_digest(password, creds["password"])

async def verify_totp(code: str) -> bool:
    secret = get_config()["main"]["web"]["credentials"]["totp_secret"]
    if not secret:
        return True
    
    generated = await totp(secret)
    return hmac.compare_digest(generated, code or "")

def issue_token() -> str:
    now = datetime.now(tz=timezone.utc)

    return jwt.encode(
        {
            "sub": "admin",
            "iat": now, 
            "exp": now + timedelta(hours=TOKEN_TTL_HOURS)
        },
        get_jwt_secret(),
        algorithm=ALGO,
    )


def require_auth(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[ALGO])
        return payload["sub"]
    except Exception:
        raise HTTPException(401, "Invalid or expired session")
