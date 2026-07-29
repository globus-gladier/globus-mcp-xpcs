from typing import Any

from pydantic import BaseModel, Field


class TransferEndpoint(BaseModel):
    endpoint_id: str = Field(description="ID of the endpoint")
    display_name: str = Field(description="Friendly name for the endpoint")
    owner_id: str = Field(description="ID of the endpoint owner")
    owner_string: str = Field(description="Identity name of the endpoint owner")
    type: str = Field(description="The type of endpoint")
    description: str | None = Field(default=None, description="A description of the endpoint")


class TransferEvent(BaseModel):
    code: str = Field(description="A code indicating the type of the event.")
    is_error: bool = Field(description="true if event is an error event")
    description: str = Field(description="A description of the event.")
    details: str = Field(description="Type specific details about the event.")
    time: str = Field(
        description=(
            "The date and time the event occurred, in ISO 8601 format"
            " (YYYY-MM-DD HH:MM:SS) and UTC."
        )
    )


class TransferSubmitResponse(BaseModel):
    task_id: str = Field(description="ID of the transfer task")


class TransferTaskProgress(BaseModel):
    task_id: str = Field(description="ID of the transfer task")
    completed: bool = Field(description="true if the task finished before the timeout")
    task: dict[str, Any] = Field(description="Raw task response data from Globus Transfer")
    events: list[TransferEvent] = Field(description="Recent task events")


class TransferDirectoryListing(BaseModel):
    filenames: list[str] = Field(description="File and directory names in the requested directory")
    basepath: str = Field(description="Shared basepath for all returned filenames")


###
# Pagination
###


class TransferList(BaseModel):
    offset: int = Field(description="Zero based offset into the result set.")
    limit: int = Field(description="Maximum number of results to return.")


class TransferEndpointList(TransferList):
    has_next_page: bool = Field(
        description="Indicates whether making a query at the next offset would yield more results",
    )
    data: list[TransferEndpoint] = Field(description="Set of transfer endpoints")


class TransferEventList(TransferList):
    data: list[TransferEvent] = Field(description="Set of transfer task events")
