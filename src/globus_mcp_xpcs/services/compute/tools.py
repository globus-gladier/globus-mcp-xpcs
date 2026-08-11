import asyncio
import time
from collections.abc import Callable
from typing import Annotated, Any, cast

import globus_sdk
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from pydantic import Field

from globus_mcp_xpcs import config
from globus_mcp_xpcs.context import GlobusContext
from globus_mcp_xpcs.services.compute.client import get_compute_client
from globus_mcp_xpcs.services.compute.schemas import (
    ComputeEndpointBasepath,
    ComputeEndpointInfo,
    ComputeTask,
    ComputeTaskBatchProgress,
)


def _task_has_outcome(task_data: dict[str, Any]) -> bool:
    status = str(task_data.get("status", "")).lower()
    if status in {"success", "failed"}:
        return True
    return task_data.get("result") is not None or task_data.get("exception") is not None


async def globus_compute_get_task_status(
    task_ids: Annotated[
        list[str],
        Field(min_length=1, description="List of task IDs to monitor."),
    ],
    ctx: Context[ServerSession, GlobusContext],
    polling_interval: Annotated[
        float,
        Field(default=2.0, gt=0, description="Seconds between status polls."),
    ] = 2.0,
    timeout_seconds: Annotated[
        int,
        Field(default=300, ge=1, description="Maximum time to wait for all tasks to complete."),
    ] = 300,
) -> ComputeTaskBatchProgress:
    """Retrieve status and results for multiple Globus Compute tasks.

    Use this to poll the task_uuids returned by run_xpcs_boost_corr. This tool polls until all
    tasks complete or the timeout is reached.
    """
    client = get_compute_client(ctx)
    task_data_by_id: dict[str, dict[str, Any]] = {}
    start_time = time.monotonic()

    try:
        while True:
            for task_id in task_ids:
                task_res = client._compute_web_client.v2.get_task(task_id)
                if hasattr(task_res, "data"):
                    task_data_by_id[task_id] = dict(cast(dict[str, Any], task_res.data))
                else:
                    task_data_by_id[task_id] = dict(cast(dict[str, Any], task_res))

            completed_tasks = sum(
                1 for task_data in task_data_by_id.values() if _task_has_outcome(task_data)
            )
            if completed_tasks == len(task_ids):
                break

            if (time.monotonic() - start_time) >= timeout_seconds:
                break

            await asyncio.sleep(polling_interval)
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to get task status: {e}") from e

    tasks: list[ComputeTask] = []
    for task_id in task_ids:
        task_data = task_data_by_id[task_id]
        result = task_data.get("result")
        if result is not None:
            try:
                result = client.fx_serializer.deserialize(result)
            except Exception as e:
                raise ToolError("Unable to deserialize result") from e

        tasks.append(
            ComputeTask(
                task_id=task_data["task_id"],
                status=str(task_data.get("status", "")),
                result=result,
                exception=task_data.get("exception"),
            )
        )

    completed_tasks = sum(1 for task in tasks if _task_has_outcome(task.model_dump()))
    total_tasks = len(task_ids)
    return ComputeTaskBatchProgress(
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        pending_tasks=total_tasks - completed_tasks,
        tasks=tasks,
    )


def list_compute_endpoints() -> list[ComputeEndpointInfo]:
    """List the configured XPCS compute endpoints and their allowed
    filesystem paths/permissions."""
    return [
        ComputeEndpointInfo(
            uuid=ep["uuid"],
            display_name=ep["display_name"],
            description=ep["description"],
            allowed_basepaths=[
                ComputeEndpointBasepath(
                    path=bp["path"],
                    permissions=bp["permissions"],
                )
                for bp in ep.get("allowed_basepaths", [])
            ],
        )
        for ep in config.COMPUTE_ENDPOINTS
    ]


ALL_COMPUTE_TOOLS: list[Callable[..., Any]] = [
    globus_compute_get_task_status,
    list_compute_endpoints,
]
