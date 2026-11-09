import re

from .text import normalize

_INJECTION = re.compile(r"ignore\b.{0,50}\b(instructions?|polic|previous)|bo qua\b.{0,50}\b(huong dan|quy dinh|chinh sach)|"
                        r"system prompt|api key|drop table|\beval\b|\bexec\b|\bglobals\b|"
                        r"reveal.{0,30}(secret|token)|tiet lo.{0,30}(khoa|token|bi mat)|"
                        r"call.{0,20}(shell|http|network)|goi.{0,20}(shell|http|network)")
_EXTERNAL = re.compile(r"\b(book|booking|pay|payment|refund|publish|published)\b|"
                       r"\b(dat ve|doi ve|huy ve|dat khach san|thanh toan|hoan tien|gui email|gui mail|gui tin nhan|xuat ban)\b")
_SENSITIVE = re.compile(r"\b(passport|ho chieu|credit card|the tin dung|so tai khoan|api key|bearer)\b")
_REDACT_KEYS = {"password", "passwd", "token", "access_token", "refresh_token", "secret", "api_key", "apikey",
                "authorization", "cookie", "address", "customer_name", "email", "card_number", "passport",
                "passport_number", "visa_number", "bank_account", "raw_message", "message", "query"}
_PHONE_KEYS = {"phone", "phone_number", "sdt"}
_PHONE_RE = re.compile(r"(?<![\w])\+?\d[\d .\-]{7,}\d(?![\w])")
_MAX_STR = 200


def injection_like(text):
    return bool(_INJECTION.search(normalize(text)))


def unsafe_user_request(text):
    return injection_like(text) or bool(_EXTERNAL.search(normalize(text))) or bool(_SENSITIVE.search(normalize(text)))


def _mask_phone(text: str) -> str:
    def repl(m):
        digits = re.sub(r"\D", "", m.group(0))
        return "***" + digits[-3:] if len(digits) >= 9 else m.group(0)
    return _PHONE_RE.sub(repl, text)


def sanitize(value, depth: int = 0):
    if depth > 5:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:50]:
            key = str(k)[:50]
            low = key.lower()
            if low in _REDACT_KEYS:
                out[key] = "[REDACTED]"
            elif low in _PHONE_KEYS and isinstance(v, str):
                out[key] = _mask_phone(v) if _PHONE_RE.search(v) else "[REDACTED]"
            else:
                out[key] = sanitize(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [sanitize(x, depth + 1) for x in list(value)[:50]]
    if isinstance(value, str):
        return _mask_phone(value)[:_MAX_STR]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:_MAX_STR]


def safe_arguments(arguments):
    safe = {}
    for key, value in arguments.items():
        if key in {"trip_id", "report_id", "traveler_id"} and isinstance(value, str):
            if re.fullmatch(r"(?:TRIP|EXP)-\d{4}-\d{3}|TRV-\d{3}", value):
                safe[key] = value
        elif key == "category" and isinstance(value, str) and value in {"travel", "expense", "visa", "insurance", "approval"}:
            safe[key] = value
        elif key == "max_results" and type(value) is int:
            safe[key] = value
        else:
            safe[key] = "[REDACTED]"
    return safe
