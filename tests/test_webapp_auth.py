import hashlib
import hmac
from urllib.parse import urlencode

from concierge.webapp.auth import validate_init_data, parse_init_data

TOKEN = "123456:TEST-TOKEN"


def sign_init_data(params: dict, token: str = TOKEN) -> str:
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**params, "hash": h})


def test_valid_init_data_passes():
    init = sign_init_data({"auth_date": "1000", "start_param": "-500",
                           "user": '{"id":42,"first_name":"Ana"}'})
    assert validate_init_data(init, TOKEN, now=1500) is True


def test_tampered_field_rejected():
    init = sign_init_data({"auth_date": "1000", "start_param": "-500"})
    tampered = init.replace("-500", "-999")
    assert validate_init_data(tampered, TOKEN, now=1500) is False


def test_wrong_token_rejected():
    init = sign_init_data({"auth_date": "1000"})
    assert validate_init_data(init, "outro:token", now=1500) is False


def test_stale_auth_date_rejected():
    init = sign_init_data({"auth_date": "1000"})
    assert validate_init_data(init, TOKEN, now=1000 + 3601) is False
    assert validate_init_data(init, TOKEN, now=1000 + 3599) is True


def test_missing_hash_or_garbage_rejected():
    assert validate_init_data("auth_date=1000", TOKEN, now=1500) is False
    assert validate_init_data("", TOKEN, now=1500) is False
    assert validate_init_data("%%%not-a-querystring", TOKEN, now=1500) is False


def test_parse_init_data_decodes():
    init = sign_init_data({"auth_date": "1000", "start_param": "-500"})
    fields = parse_init_data(init)
    assert fields["start_param"] == "-500"
    assert "hash" in fields
