from pydantic import BaseModel, Field


class CollectionBasepath(BaseModel):
    path: str = Field(description="Allowed filesystem path on the collection.")
    permissions: str = Field(description="Permission flags for this path, e.g. 'r', 'w', or 'rw'.")


class CollectionInfo(BaseModel):
    uuid: str = Field(description="UUID of the Globus collection.")
    display_name: str = Field(description="Human-readable name of the collection.")
    description: str = Field(description="Description of the collection and its purpose.")
    collection_basepath: str = Field(
        description="Root path of the collection on the storage system."
    )
    allowed_basepaths: list[CollectionBasepath] = Field(
        description="Filesystem paths this collection is permitted to access."
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


class XPCSBoostCorrSubmitResponse(BaseModel):
    task_uuids: list[str] = Field(description="Task UUIDs for each submitted compute job.")
