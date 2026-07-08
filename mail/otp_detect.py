import re
from email.utils import parseaddr


def _strip_html(html: str) -> str:
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.I)
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


def _sender_address(from_header: str) -> str:
    _, addr = parseaddr(from_header or "")
    return addr or from_header or ""


def detect_otp(subject: str, body: str, from_header: str = "") -> dict:
    text = body or ""
    plain_from_html = _strip_html(text) if "<" in text and ">" in text else text
    haystack = f"{subject}\n{text}\n{plain_from_html}".lower()
    search_space = f"{subject}\n{text}\n{plain_from_html}"

    keyword_re = re.compile(
        r"(otp|one[\s-]?time[\s-]?password|one[\s-]?time[\s-]?code|single[\s-]?use[\s-]?code|"
        r"temporary[\s-]?code|verification\s+code|verify\s+(your\s+)?(code|email|account|identity)|"
        r"security\s+code|login\s+code|log[\s-]?in\s+code|sign[\s-]?in\s+code|sign[\s-]?up\s+code|"
        r"access\s+code|auth(?:entication)?\s+code|2fa|two[\s-]?factor|confirmation\s+code|"
        r"confirm\s+your\s+(email|account|identity)|passcode|pin\s+code|your\s+code\s+is|"
        r"use\s+the\s+code|enter\s+the\s+code|use\s+this\s+code|magic\s+(link|code)|recovery\s+code|"
        r"engangskode|engangskoden|engångskod|engångskoden|einmal(?:code|kennwort)|"
        r"verificerings(?:code|kode)|bevestigingscode|eenmalige\s+code|codigo|código|"
        r"code\s+de\s+(?:v[eé]rification|s[eé]curit[eé]|confirmation|connexion)|codice|"
        r"kod\s+(?:weryfikacyjny|jednorazowy)|kertakäyttö(?:inen\s+)?(?:koodi|salasana)|"
        r"одноразов(?:ый\s+код|ого\s+кода)|一次性(?:验证码|代码)|ワンタイム(?:コード|パスワード)|"
        r"일회용\s*(?:코드|비밀번호))",
        re.I,
    )

    has_keyword = bool(keyword_re.search(haystack))
    from_str = _sender_address(from_header)
    is_ms_security = bool(re.search(r"accountprotection\.microsoft\.com", from_str, re.I))

    code_patterns = [
        re.compile(r"single-use code is:\s*(\d{6})", re.I),
        re.compile(r"your single-use code is:\s*(\d{6})", re.I),
        re.compile(r"security code:\s*(\d{6})", re.I),
        re.compile(r":\s*(\d{6})\b"),
        re.compile(r"engangskoden?\s*(?:din\s*)?(?:er\s*)?[:\s]+(\d{6})", re.I),
        re.compile(r"engångskoden?\s*(?:din\s*)?(?:är\s*)?[:\s]+(\d{6})", re.I),
        re.compile(r"einmal(?:code|kennwort)[^\d]{0,40}(\d{6})", re.I),
        re.compile(r"(?:verificerings|bevestigings)(?:code|kode)[^\d]{0,40}(\d{6})", re.I),
        re.compile(r"c[oó]digo(?:\s+de\s+(?:un\s+solo\s+uso|verificaci[oó]n))?[^\d]{0,40}(\d{6})", re.I),
        re.compile(r"code\s+(?:de\s+)?(?:v[eé]rification|s[eé]curit[eé]|unique|confirmation)[^\d]{0,40}(\d{6})", re.I),
        re.compile(r"\b(?:code|otp|pin|passcode|kode|codigo|código)\b\s*(?:is\s+|er\s+|är\s+|:\s*|=\s*)[`\"']?(\d{6})[`\"']?", re.I),
        re.compile(r"\b(\d{6})\b"),
    ]

    code = None
    for pattern in code_patterns:
        match = pattern.search(search_space)
        if match and match.group(1):
            code = match.group(1)
            break

    is_otp = (
        has_keyword
        or bool(
            re.search(
                r"\b(otp|verification|verify|2fa|passcode|one[\s-]?time|single[\s-]?use|"
                r"sign[\s-]?in\s+code|login\s+code|security\s+code|confirm|engangskode|"
                r"engangskoden|engångskod|einmalcode|verificerings|bevestigings|codigo|código)\b",
                subject,
                re.I,
            )
        )
        or is_ms_security
    )

    if is_otp and not code and is_ms_security:
        match = re.search(r"\b(\d{6})\b", search_space)
        if match:
            code = match.group(1)

    if not code:
        match = re.search(r":\s*(\d{6})\b", search_space)
        if match:
            code = match.group(1)

    if code and not is_otp and (is_ms_security or re.search(r":\s*\d{6}\b", search_space)):
        is_otp = True

    reason = None
    if is_otp:
        if has_keyword:
            reason = "keyword"
        elif is_ms_security:
            reason = "microsoft-sender"
        else:
            reason = "colon-code"

    return {
        "is_otp": is_otp,
        "code": code if is_otp else None,
        "reason": reason,
    }
