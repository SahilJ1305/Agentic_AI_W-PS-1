# from fastapi import FastAPI, Request
# from fastapi.middleware.cors import CORSMiddleware
# import os
# from starlette.middleware.sessions import SessionMiddleware
# from contextlib import asynccontextmanager

# from database.postgresConn import engine, Base
# from models import all_model
# from router import user_routes, auth_routes, telegram_routes
# from services.telegram_service import telegram_service

# # Create database tables
# all_model.Base.metadata.create_all(bind=engine)

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     await telegram_service.start()

#     try:
#         yield
#     finally:
#         await telegram_service.stop()

# app = FastAPI(
#     title="Kurukshetra Backend API",
#     description="Backend API Kurukshetra"
# )

# # 1. SESSION MIDDLEWARE
# # Required for Google OAuth redirect state management
# app.add_middleware(
#     SessionMiddleware, 
#     secret_key=os.getenv("SESSION_SECRET", "super-secret-key-change-me"),
#     same_site="lax",
#     https_only=False  # Set to True in production with HTTPS
# )

# # 2. CORS ORIGINS
# # Added Docker container origins (http://localhost:8080) and wildcard allowance for development
# origins = [
#     "http://localhost:5173",
#     "http://127.0.0.1:5173",
#     "http://localhost:8080",
#     "http://127.0.0.1:8080",
# ]

# # Add CORS middleware
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=origins,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# @app.get("/")
# def root():
#     return {"message": "Welcome to Kurukshetra!"}

# # Include routers
# app.include_router(auth_routes.router)
# app.include_router(user_routes.router)
# app.include_router(telegram_routes.router)



import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env before importing services that read environment variables.
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from database.postgresConn import engine
from models import all_model
from router import user_routes, auth_routes, telegram_routes
from services.telegram_service import telegram_service


# Create database tables
all_model.Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting Telegram service...")

    await telegram_service.start()

    print("Telegram service started.")

    try:
        yield
    finally:
        print("Stopping Telegram service...")
        await telegram_service.stop()


# IMPORTANT: Connect the lifespan function here.
app = FastAPI(
    title="Kurukshetra Backend API",
    description="Backend API Kurukshetra",
    lifespan=lifespan,
)


# Session middleware
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv(
        "SESSION_SECRET",
        "super-secret-key-change-me",
    ),
    same_site="lax",
    https_only=False,
)


# CORS configuration
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "Welcome to Kurukshetra!"}


# Existing routers
app.include_router(auth_routes.router)
app.include_router(user_routes.router)

# Telegram router
app.include_router(telegram_routes.router)
