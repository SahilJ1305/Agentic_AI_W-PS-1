"""
Accounts service for Cadence: sign-up, login (password or Google), password reset.

Users live in Postgres (DATABASE_URL). Login returns an HS256 JWT signed with
SECRET_KEY; the Cadence API (app/, port 8000) checks the same token, so both
services must share SECRET_KEY.

    cd backend && uvicorn main:app --port 8001
"""
import os

from dotenv import load_dotenv

# Load .env before importing modules that read environment variables.
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from database.postgresConn import engine
from models import all_model
from router import auth_routes, user_routes


all_model.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Cadence accounts API",
    description="Users and login for the Cadence dashboard",
)

# Google OAuth keeps its redirect state in the session cookie.
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET") or os.environ["SECRET_KEY"],
    same_site="lax",
    https_only=False,
)

frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
origins = sorted({
    frontend_url,
    "http://localhost:5173",
    "http://127.0.0.1:5173",
})
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"service": "cadence-accounts", "status": "ok"}


app.include_router(auth_routes.router)
app.include_router(user_routes.router)
