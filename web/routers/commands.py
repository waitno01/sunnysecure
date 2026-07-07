from web.models import RealCommandsRequest, FakeCommandRequest, RenameCommandRequest
from web.config import require_auth, get_config
from fastapi import APIRouter, Depends, HTTPException
import json, os, re, random, string

router = APIRouter()

name_re = re.compile(r"^[-_\w]{1,32}$", re.UNICODE)

def validate_command_name(alias: str) -> str:
    alias = alias.strip()
    if not name_re.match(alias) or alias != alias.lower():
        raise HTTPException(
            400,
            f"Invalid command name '{alias}'. Custom names need to follow discords command naming convention."
        )
    return alias


@router.get("/api/commands")
def get_commands(user: str = Depends(require_auth)):
    bc = get_config()["web"]

    enabled = bc["enabled_commands"]
    available = []

    if os.path.isdir("cogs"):
        for fname in sorted(os.listdir("cogs")):
            if fname.endswith(".py") and not fname.startswith("_"):
                available.append(fname[:-3])

    return {
        "real": {
            "available": available, 
            "enabled": enabled["real"]
        },
        "fake": enabled["fake"],
        "aliases": enabled["aliases"],
    }


@router.post("/api/commands/real")
def update_real_commands(body: RealCommandsRequest, user: str = Depends(require_auth)):
    bc = get_config()["web"]

    new_commands = {k: bool(v) for k, v in body.commands.items()}
    bc.setdefault("enabled_commands", {})["real"] = new_commands

    with open("config/bot.json", "w") as f:
        json.dump(bc, f, indent=2)
    
    return {"ok": True}


@router.post("/api/commands/fake")
def add_fake_command(body: FakeCommandRequest, user: str = Depends(require_auth)):
    bc = get_config()["web"]

    bc.setdefault("enabled_commands", {}).setdefault("fake", {})[body.title] = {
        "title": body.title,
        "description": body.description,
        "response": body.response,
    }

    with open("config/bot.json", "w") as f:
        json.dump(bc, f, indent=2)

    return {"ok": True}


@router.post("/api/commands/aliases")
def update_command_aliases(body: RenameCommandRequest, user: str = Depends(require_auth)):
    bc = get_config()["web"]
    existing = bc.setdefault("enabled_commands", {}).setdefault("aliases", {})
    for cmd, alias in body.aliases.items():
        existing[cmd] = validate_command_name(alias) if alias else cmd
    with open("config/bot.json", "w") as f:
        json.dump(bc, f, indent=2)
    return {"ok": True}

@router.post("/api/commands/aliases/reset")
def reset_command_aliases(body: RenameCommandRequest, user: str = Depends(require_auth)):
    bc = get_config()["web"]
    existing = bc.setdefault("enabled_commands", {}).setdefault("aliases", {})
    for cmd, _ in body.aliases.items():
        existing[cmd] = cmd
    with open("config/bot.json", "w") as f:
        json.dump(bc, f, indent=2)
    return {"ok": True}

@router.post("/api/commands/aliases/anonymize")
def anonymize_command_aliases(user: str = Depends(require_auth)):
    bc = get_config()["web"]
    existing = bc.setdefault("enabled_commands", {}).setdefault("aliases", {})

    available = []
    if os.path.isdir("cogs"):
        for fname in sorted(os.listdir("cogs")):
            if fname.endswith(".py") and not fname.startswith("_"):
                available.append(fname[:-3])

    used = set()
    for cmd in available:
        while True:
            alias = "".join(random.choices(string.ascii_lowercase, k=8))
            if alias not in used:
                break
        used.add(alias)
        existing[cmd] = alias

    with open("config/bot.json", "w") as f:
        json.dump(bc, f, indent=2)
    return {"ok": True}

@router.delete("/api/commands/fake/{name:path}")
def delete_fake_command(name: str, user: str = Depends(require_auth)):
    bc = get_config()["web"]

    bc.setdefault("enabled_commands", {}).setdefault("fake", {}).pop(name, None)
    with open("config/bot.json", "w") as f:
        json.dump(bc, f, indent=2)

    return {"ok": True}
