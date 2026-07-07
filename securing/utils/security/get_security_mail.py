import httpx
import re

async def get_security_email(session: httpx.AsyncClient) -> str:
    # Gets the security mail from the account
    
    proofs = await session.get(
        "https://account.live.com/proofs/manage/additional?mkt=en-US&refd=account.microsoft.com&refp=security",
        headers = {
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://login.live.com/"
        }
    )

    security_email = re.search(r'"displayProofName"\s*:\s*"([^"]+)"', proofs.text).group(1)
    return security_email.replace(r"\u0040", "@")