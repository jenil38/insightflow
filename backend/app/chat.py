"""
AI Copilot routes: ask, read history, clear history, and fetch suggestions.

All logic lives in services/chat_service.py, which reads its configuration from
`settings` (not os.getenv) and persists every turn to the ChatMessage table.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from . import auth, models, schemas
from .core.limits import check_copilot_rate
from .database import get_db
from .deps import get_owned_dataset
from .services.chat_service import ChatService

router = APIRouter(prefix="/datasets", tags=["chat"])


@router.post("/{dataset_id}/chat", response_model=schemas.ChatResponse)
def chat_with_dataset(
    body: schemas.ChatRequest,
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    check_copilot_rate(db, current_user.id)
    return ChatService(db).ask(dataset, current_user.id, body.question)


@router.get("/{dataset_id}/chat/history", response_model=list[schemas.ChatMessageOut])
def chat_history(
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    return ChatService(db).history(dataset.id, current_user.id)


@router.delete("/{dataset_id}/chat/history", status_code=status.HTTP_200_OK)
def clear_chat_history(
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    deleted = ChatService(db).clear_history(dataset.id, current_user.id)
    return {"deleted": deleted, "detail": f"Cleared {deleted} message(s)."}


@router.get("/{dataset_id}/chat/suggestions", response_model=schemas.SuggestedQuestions)
def chat_suggestions(
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
):
    """Suggested questions derived from this dataset's actual column types, plus
    whether the Copilot is configured at all - so the UI can show an honest
    disabled state instead of a chat box that always errors."""
    return ChatService(db).suggested_questions(dataset)
