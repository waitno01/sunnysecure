import secrets
import string


def generate_ms_password(length: int = 14) -> str:
    """Letters + digits only, with mixed case (Microsoft complexity).

    Upstream Sal/autosecure used uuid.hex (lowercase only). Live tests show
    RecoverUser accepts that format in the API response, but mixed-case
    alnum is safer against MS complexity / banned-password checks.
    No symbols — per product requirement.
    """
    if length < 12:
        length = 12

    alphabet = string.ascii_letters + string.digits
    for _ in range(50):
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in pwd)
            and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd)
        ):
            return pwd

    # Extremely unlikely fallback
    return (
        secrets.choice(string.ascii_lowercase)
        + secrets.choice(string.ascii_uppercase)
        + secrets.choice(string.digits)
        + "".join(secrets.choice(alphabet) for _ in range(max(0, length - 3)))
    )
