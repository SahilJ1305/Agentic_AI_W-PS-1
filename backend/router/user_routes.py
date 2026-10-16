# router/user_routes.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from database.postgresConn import get_db
# FIX: Import models and schemas with aliases to avoid name collisions
from models.all_model import User as UserModel
from schemas.all_schema import UserResponse, UserCreate, TokenData
from auth import hashing, oauth2

router = APIRouter(
    prefix="/api/users",
    tags=["Users"]
)

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(request: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(UserModel).filter(UserModel.email == request.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with email {request.email} already exists."
        )

    new_user = UserModel(
        email=request.email,
        hashed_password=hashing.Hash.bcrypt(request.password),
        full_name=request.full_name,
       
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user

@router.get("/me", response_model=UserResponse)
def get_current_user_profile(
    db: Session = Depends(get_db),
    # FIX: Correctly type hint the dependency return value
    current_user: TokenData = Depends(oauth2.get_current_user)
):
    user = db.query(UserModel).filter(UserModel.email == current_user.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found."
        )
    return user

@router.get("/", response_model=List[UserResponse])
def get_all_users(db: Session = Depends(get_db)):
    users = db.query(UserModel).all()
    return users

@router.put("/me", response_model=UserResponse)
def update_current_user(
    update_data: dict,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(oauth2.get_current_user)
):
    user_to_update = db.query(UserModel).filter(UserModel.email == current_user.username).first()
    if not user_to_update:
        raise HTTPException(status_code=404, detail="User not found")
    
    for key, value in update_data.items():
        if key in ["full_name"]:
            setattr(user_to_update, key, value)
            
    db.commit()
    db.refresh(user_to_update)
    return user_to_update