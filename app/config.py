"""
app/config.py — pydantic-settings; all env vars from spec §15.

Reads from .env automatically when python-dotenv is installed.
All settings are available as `from app.config import settings`.
"""
from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- Telegram ---------------------------------------------------
    telegram_bot_token: str = ""
    telegram_bot_username: str = "cadence_coord_bot"
    telegram_group_chat_id: int | None = None

    # ---- Login (shared with backend/) -------------------------------
    secret_key: str = ""                      # SECRET_KEY: same value the backend signs JWTs with
    frontend_url: str = "http://localhost:5173"

    # ---- Web server -------------------------------------------------
    app_host: str = "127.0.0.1"             # 0.0.0.0 inside a container
    app_port: int = 8000
    cors_origins: str = ""                  # extra allowed website origins, comma separated

    # ---- Storage ----------------------------------------------------
    database_path: str = "./data/cadence.db"
    timezone: str = "Asia/Kolkata"

    # ---- LLM: which primary provider --------------------------------
    llm_provider: str = "ollama"            # "ollama" or "azure"

    # ---- LLM: Azure AI Foundry --------------------------------------
    azure_ai_endpoint: str = ""
    azure_ai_api_key: str = ""
    azure_ai_api_version: str = ""
    azure_coordinator_deployment: str = ""
    azure_planner_deployment: str = ""

    # ---- LLM: Ollama primary ----------------------------------------
    ollama_base_url: str = "http://localhost:11435"
    coordinator_model: str = ""
    planner_model: str = ""
    coordinator_num_ctx: int = 8192
    planner_num_ctx: int = 32768
    coordinator_think: bool = False
    planner_think: bool = True
    ollama_keep_alive: str = "24h"

    # ---- LLM: OpenCode Console fallback -----------------------------
    opencode_base_url: str = "https://opencode.ai/inference/openai/v1"
    opencode_api_key: str = ""
    opencode_model: str = "glm-5.3-flash-free"

    # ---- Timeouts (seconds) -----------------------------------------
    llm_timeout_s: int = 12
    planner_timeout_s: int = 120

    # ---- Behaviour --------------------------------------------------
    demo_mode: bool = True
    followup_cron: str = "0 10,18 * * *"
    digest_cron: str = "0 21 * * *"

    nudge_after_min: int = 120
    blocker_escalate_min: int = 180
    risk_blocked_min: int = 120
    quiet_min: float = 10.0
    undo_window_min: int = 30
    debounce_s: float = 1.5            # wait this long for a person's follow-up line before reading

    clarify_threshold: float = 0.6
    edge_auto_accept: float = 0.8
    runtime_edge_min: float = 0.7

    personalise_followups: bool = False

    # ---- Git claim checker (app/tools/git_checker.py) ---------------
    github_repo: str = ""                   # "owner/repo"; empty disables the checker
    github_token: str = ""                  # optional for public repos (60 req/h without)
    github_api_url: str = "https://api.github.com"
    github_timeout_s: float = 8.0
    git_check_grace_hours: float = 24.0     # count work from this long before the task existed

    @property
    def git_check_enabled(self) -> bool:
        return bool(self.github_repo.strip())

    # ---- Demo-mode overrides ----------------------------------------
    @property
    def effective_nudge_after_min(self) -> float:
        return 2.0 if self.demo_mode else self.nudge_after_min

    @property
    def effective_blocker_escalate_min(self) -> float:
        return 4.0 if self.demo_mode else self.blocker_escalate_min

    @property
    def effective_risk_blocked_min(self) -> float:
        return 2.0 if self.demo_mode else self.risk_blocked_min

    @property
    def effective_quiet_min(self) -> float:
        return 0.5 if self.demo_mode else self.quiet_min

    @field_validator("llm_provider")
    @classmethod
    def known_provider(cls, value: str) -> str:
        value = (value or "ollama").strip().lower()
        if value not in ("ollama", "azure"):
            raise ValueError("LLM_PROVIDER must be ollama or azure")
        return value

    @field_validator("telegram_group_chat_id", mode="before")
    @classmethod
    def empty_group_chat_is_none(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @field_validator("clarify_threshold", "edge_auto_accept", "runtime_edge_min")
    @classmethod
    def must_be_0_to_1(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        return v


settings = Settings()
