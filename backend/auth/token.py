from jose import JWTError, jwt
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone

from schemas.all_schema import TokenData

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is not set. Use the same value as the Cadence API (root .env), "
        "otherwise the dashboard rejects every login."
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "720"))


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str, credential_exception):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # print("Decoded payload:", payload) 
        username = payload.get("sub")
        if username is None:
            raise credential_exception
        token_data = TokenData(username=username) 
    except JWTError as e:
        print("JWT error:", e)
        raise credential_exception
    
    return token_data
