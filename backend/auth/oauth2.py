#auth/oauth2.py
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy.orm import Session # <--- Import Session

from database.postgresConn import get_db # <--- Import DB Connection
from models.all_model import User as UserModel # <--- Import User Model
from auth import token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def get_current_user(data: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    # print("Raw token received:", data) 
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = token.verify_token(data, credentials_exception)

    # 2. CRITICAL FIX: Fetch the REAL User from Database using the email
    user = db.query(UserModel).filter(UserModel.email == token_data.username).first()
    
    if user is None:
        raise credentials_exception
        
    # 3. Return the full Database Object (contains .id, .profile, etc.)
    return user
