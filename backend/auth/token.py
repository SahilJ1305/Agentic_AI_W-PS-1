from jose import JWTError, jwt  
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone

from schemas.all_schema import TokenData

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY") or "abc"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 210



def create_access_token(data: dict, expires_delta: timedelta = timedelta(minutes=60)):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=60)
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