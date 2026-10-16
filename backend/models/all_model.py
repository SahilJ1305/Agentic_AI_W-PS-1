
import enum
from sqlalchemy import (
    Column, Integer, String, Float, Date, Enum,
    ForeignKey, DateTime, Text, Boolean
)
from sqlalchemy.sql import func
from typing import Optional

# Import the single, shared Base object
from database.postgresConn import Base


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    
    # Reset Password Tokens
    reset_token = Column(String, nullable=True)         
    reset_token_expiry = Column(DateTime(timezone=True), nullable=True) 
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())



