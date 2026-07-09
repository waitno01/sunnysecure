import secrets
import string


def generate_ms_password(length: int = 16) -> str:
    """Generate a Microsoft-safe recovery password.

    Matches the working dona-fork approach (secrets.token_urlsafe):
    A-Za-z0-9 plus _ and - only. No $ ? & @ # — those often get rejected
    or mangled by RecoverUser even when the API still returns a recoveryCode.
    """
    if length < 12:
        length = 12

    # token_urlsafe alphabet without padding
    alphabet = string.ascii_letters + string.digits + "_-"
    # Prefer urlsafe; ensure mixed case + digit for MS complexity heuristics
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in pwd)
            and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd)
        ):
            return pwd
