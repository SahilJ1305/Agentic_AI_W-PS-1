import os
import uuid
import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from authlib.integrations.starlette_client import OAuth

from database.postgresConn import get_db
from models.all_model import User as UserModel
from schemas.all_schema import TokenWithUser, ForgotPasswordRequest, VerifyOtpRequest, ResetPasswordRequest
from auth import hashing, token
from utils.email_otp import send_otp_email


router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"]
)

# --- Configuration for Google OAuth ---
oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# --- STANDARD LOGIN ---

@router.post("/login", response_model=TokenWithUser)
def login(
    request: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.query(UserModel).filter(UserModel.email == request.username).first()

    if not user or not hashing.Hash.verify(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    access_token = token.create_access_token(data={
        "sub": user.email,
        "user_id": user.id,
    })

    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "user": user 
    }

# --- GOOGLE OAUTH FLOW ---

@router.get("/login/google")
async def login_via_google(request: Request):
    """Redirects the user to Google for OAuth authentication."""
    redirect_uri = request.url_for('auth_google_callback')
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback", name="auth_google_callback")
async def auth_google_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token_google = await oauth.google.authorize_access_token(request)
        user_info = token_google.get('userinfo')
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Could not validate Google credentials: {e}")

    user_email = user_info['email']
    user = db.query(UserModel).filter(UserModel.email == user_email).first()

    # Create new user if not registered via standard signup
    if not user:
        new_user = UserModel(
            email=user_email,
            full_name=user_info.get('name'),
            hashed_password=hashing.Hash.bcrypt(str(uuid.uuid4())),
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        user = new_user

    # Generate JWT App Token
    app_jwt = token.create_access_token(
        data={"sub": user.email, "user_id": user.id}
    )

    return HTMLResponse(f"""
        <script>
            window.opener.postMessage({{ "token": "{app_jwt}", "user": {user.to_json()} }}, "*");
            window.close();
        </script>
    """)

# Helper to add a to_json method 
def user_to_json(self):
    import json
    return json.dumps({
        "id": self.id,
        "email": self.email,
        "full_name": self.full_name,
    })
UserModel.to_json = user_to_json


# --- FORGOT PASSWORD FLOW ---

@router.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(UserModel).filter(UserModel.email == request.email).first()
    
    # Check if account exists
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account found with this email address."
        )

    # Generate 6-digit OTP
    otp = str(random.randint(100000, 999999))
    user.reset_token = otp
    user.reset_token_expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.commit()

    # Attempt email delivery
    email_sent = send_otp_email(user.email, otp)
    if not email_sent:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send OTP email. Please try again later."
        )

    return {"message": "OTP sent successfully to your email."}


@router.post("/verify-otp")
def verify_otp(request: VerifyOtpRequest, db: Session = Depends(get_db)):
    user = db.query(UserModel).filter(UserModel.email == request.email).first()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if str(user.reset_token) != request.otp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OTP")

    current_time = datetime.now(timezone.utc)
    expiry = user.reset_token_expiry
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    if not expiry or expiry < current_time:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP has expired.")

    return {"message": "OTP verified successfully. Proceed to reset password."}


@router.post("/reset-password")
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(UserModel).filter(UserModel.email == request.email).first()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.reset_token != request.otp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid request. OTP mismatch.")
        
    current_time = datetime.now(timezone.utc)
    expiry = user.reset_token_expiry
    if expiry and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    if expiry < current_time:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP has expired.")

    # Update Password
    user.hashed_password = hashing.Hash.bcrypt(request.new_password)
    
    # Clear Token
    user.reset_token = None
    user.reset_token_expiry = None
    db.commit()
    
    return {"message": "Password reset successfully. Please login with new password."}