from pydantic import BaseModel, Field


class XPCSBoostCorrSubmitResponse(BaseModel):
    task_ids: list[str] = Field(description="Task UUIDs from the submitted boost corr jobs.")
    task_group_id: str = Field(description="Task group UUID for the submitted boost corr job.")
