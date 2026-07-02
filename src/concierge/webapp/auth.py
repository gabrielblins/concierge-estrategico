import hashlib
import hmac
import time
from urllib.parse import parse_qsl


def parse_init_data(init_data: str) -> dict:
    try:
        return dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return {}


def validate_init_data(init_data, bot_token, max_age=3600, now=None):
    fields = parse_init_data(init_data)
    received_hash = fields.pop("hash", None)
    if not received_hash:
        return False
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        return False
    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError:
        return False
    current = now if now is not None else time.time()
    return (current - auth_date) <= max_age
