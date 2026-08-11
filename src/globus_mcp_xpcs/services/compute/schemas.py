from pydantic import BaseModel, Field, JsonValue


class ComputeEndpoint(BaseModel):
    endpoint_id: str = Field(description="ID of the endpoint")
    name: str = Field(description="The endpoint name")
    display_name: str = Field(description="Friendly name for the endpoint")
    owner_id: str = Field(description="ID of the endpoint owner")


class ComputeFunctionRegisterResponse(BaseModel):
    function_id: str = Field(description="ID of the registered function")


class ComputeSubmitResponse(BaseModel):
    task_id: str = Field(description="ID of the task")


class ComputeTask(BaseModel):
    task_id: str = Field(description="ID of the task")
    status: str = Field(description="The status of the task.")
    result: JsonValue = Field(
        description="When the task status is 'success', this will contain the task result.",
    )
    exception: str | None = Field(
        default=None,
        description="When the task status is 'failed', this will contain the exception traceback.",
    )


class ComputeEndpointBasepath(BaseModel):
    path: str = Field(description="Allowed filesystem path on the endpoint.")
    permissions: str = Field(description="Permission flags for this path, e.g. 'r', 'w', or 'rw'.")


class ComputeEndpointInfo(BaseModel):
    uuid: str = Field(description="UUID of the compute endpoint.")
    display_name: str = Field(description="Human-readable name of the endpoint.")
    description: str = Field(description="Description of the endpoint and its purpose.")
    allowed_basepaths: list[ComputeEndpointBasepath] = Field(
        description="Filesystem paths this endpoint is permitted to access."
    )


class ComputeTaskBatchProgress(BaseModel):
    total_tasks: int = Field(description="Total number of task IDs requested.")
    completed_tasks: int = Field(description="Number of tasks that have completed.")
    pending_tasks: int = Field(description="Number of tasks still pending completion.")
    tasks: list[ComputeTask] = Field(description="Status and result details for each task.")
