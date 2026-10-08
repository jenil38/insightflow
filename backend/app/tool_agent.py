"""
Tool-calling agent route (Phase 1).

Separate from both the Copilot (`chat.py` / `chat_service.py`) and Guided
Analysis (`agent.py` / `agent_service.py`): neither of those changes. This is
a third, additional way to ask a question about a dataset, where the model
chooses which of the tools in `tool_registry.py` to call rather than being
handed a fixed statistics block (the Copilot) or running a fixed pipeline
(Guided Analysis).

All logic lives in services/tool_agent_service.py. The route's job is just
auth, dataset ownership, and shaping the ORM result into the response schema.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from . import auth, models, schemas
from .database import get_db
from .deps import get_owned_dataset
from .services.tool_agent_service import ToolAgentService

router = APIRouter(prefix="/datasets", tags=["tool-agent"])


@router.post("/{dataset_id}/agent/ask", response_model=schemas.AgentAskResponse)
def ask_agent(
    body: schemas.AgentAskRequest,
    dataset: models.Dataset = Depends(get_owned_dataset),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Ask the tool-calling agent a question about this dataset.

    `allow_actions=true` additionally permits the agent to apply the
    recommended cleaning or train a model; the two action tools are not even
    offered to the model when this is false (see `tool_registry.tools_for`).
    """
    run = ToolAgentService(db).ask(
        dataset, current_user.id, body.question, allow_actions=body.allow_actions
    )
    return run
