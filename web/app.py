from web.routers import config_ep, auth, accounts, stats, emails, secure, shares, bot, commands
from web.limiter import limiter
from slowapi.middleware import SlowAPIMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
import os

app = FastAPI()

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(config_ep.router)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(stats.router)
app.include_router(emails.router)
app.include_router(secure.router)
app.include_router(shares.router)
app.include_router(bot.router)
app.include_router(commands.router)
