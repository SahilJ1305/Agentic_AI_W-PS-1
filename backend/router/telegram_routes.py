from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from telegram.error import TelegramError

from services.telegram_service import telegram_service

router = APIRouter(
    prefix="/api/telegram",
    tags=["Telegram"]
)


class TelegramFollowUp(BaseModel):
    chat_id: int
    owner: str = Field(min_length=1)
    task: str = Field(min_length=1)


@router.get("/participants")
async def get_participants():
    return {
        "participants": list(
            telegram_service.participants.values()
        )
    }


@router.post("/follow-up")
async def send_follow_up(payload: TelegramFollowUp):
    text = (
        f"Hi {payload.owner}! 👋\n\n"
        f"Task: {payload.task}\n\n"
        "What is the current status of this task? "
        "Please share your progress or any blockers."
    )

    try:
        await telegram_service.send_message(
            chat_id=payload.chat_id,
            text=text,
        )

        return {
            "success": True,
            "message": "Telegram follow-up sent successfully",
        }

    except TelegramError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Telegram API error: {exc}",
        )
