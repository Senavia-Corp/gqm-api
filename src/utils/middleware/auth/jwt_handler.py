import jwt
import os
from datetime import datetime, timedelta, timezone

LOGIN_SECRET_KEY = os.getenv("SECRET_KEY")
REFRESH_SECRET_KEY = os.getenv("REFRESH_SECRET_KEY")
ACCESS_EXPIRE_MIN = int(os.getenv("ACCESS_TOKEN_EXPIRES_MIN", 60))
REFRESH_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRES_DAYS", 7))

ALGORITHM = "HS256"


def create_access_token(data: dict):
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_EXPIRE_MIN)
    payload.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    })
    return jwt.encode(payload, LOGIN_SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict):
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_EXPIRE_DAYS)
    payload.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh"
    })
    return jwt.encode(payload, REFRESH_SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str):
    try:
        return jwt.decode(token, LOGIN_SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        return None


def decode_refresh_token(token: str):
    try:
        return jwt.decode(token, REFRESH_SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        return None
