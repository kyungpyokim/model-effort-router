import hashlib
import hmac

SECRET = b"dev-secret"
INVALID_TOKEN_MESSAGE = "invalid token"


def make_token(user: str) -> str:
    sig = hmac.new(SECRET, user.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{user}.{sig}"


def verify_token(token: str) -> str:
    """Returns the user name or raises PermissionError."""
    user, _, sig = token.rpartition(".")
    expected = make_token(user).rpartition(".")[2] if user else ""
    if not user or not hmac.compare_digest(sig, expected):
        raise PermissionError(INVALID_TOKEN_MESSAGE)
    return user
