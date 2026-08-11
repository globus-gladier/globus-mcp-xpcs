from pydantic import BaseModel, Field


class XPCSBoostCorrSubmitResponse(BaseModel):
    task_uuids: list[str] = Field(description="Task UUIDs for each submitted compute job.")
