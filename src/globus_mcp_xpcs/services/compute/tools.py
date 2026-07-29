import asyncio
import time
from collections.abc import Callable
from typing import Annotated, Any, Literal, cast

import globus_sdk
from globus_compute_sdk.serialize import JSONData
from globus_compute_sdk.serialize.facade import validate_strategylike
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from pydantic import Field

from globus_mcp_xpcs.context import GlobusContext
from globus_mcp_xpcs.services.compute.client import get_compute_client
from globus_mcp_xpcs.services.compute.schemas import (
    ComputeEndpoint,
    ComputeFunctionRegisterResponse,
    ComputeSubmitResponse,
    ComputeTask,
    ComputeTaskBatchProgress,
)


def globus_compute_list_endpoints(
    role: Annotated[
        Literal["any", "owner"],
        Field(
            default="any",
            description=(
                "Filter returned list by the user's association to endpoints."
                " Specify 'any' (default) to return all endpoints that the user"
                " can submit tasks to. Specify 'owner' to only return endpoints"
                " that the user owns."
            ),
        ),
    ],
    ctx: Context[ServerSession, GlobusContext],
) -> list[ComputeEndpoint]:
    """List Globus Compute endpoints that the user has access to."""
    client = get_compute_client(ctx)

    try:
        res = client.get_endpoints(role=role)
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to get endpoints: {e}") from e

    endpoints = []
    for ep in res:
        endpoint = ComputeEndpoint(
            endpoint_id=ep["uuid"],
            name=ep["name"],
            display_name=ep["display_name"],
            owner_id=ep["owner"],
        )
        endpoints.append(endpoint)

    return endpoints


def globus_compute_register_python_function(
    function_code: Annotated[str, Field(description="The text of the Python function source code")],
    function_name: Annotated[str, Field(description="The name of the Python function")],
    description: Annotated[
        str | None,
        Field(default=None, description="An optional description of the Python function"),
    ],
    public: Annotated[
        bool,
        Field(
            description="Indicates whether the Python function can be used by others",
            default=False,
        ),
    ],
    ctx: Context[ServerSession, GlobusContext],
) -> ComputeFunctionRegisterResponse:
    """Register a Python function with Globus Compute.

    Use globus_compute_submit_task to run the registered Python function on an endpoint.
    """
    client = get_compute_client(ctx)

    try:
        function_id = client.register_source_code(
            source=function_code,
            function_name=function_name,
            description=description,
            public=public,
        )
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to register Python function: {e}") from e

    return ComputeFunctionRegisterResponse(function_id=function_id)


_SHELL_FUNCTION_TEMPLATE = """
def {function_name}(*args, **kwargs):
    import subprocess
    try:
        completed = subprocess.run(
            '''{command}'''.format(*args, **kwargs),
            shell=True,
            capture_output=True,
            text=True,
            timeout={timeout},
        )
        return {{
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }}
    except subprocess.TimeoutExpired:
        return {{
            "returncode": -1,
            "stdout": "",
            "stderr": "Command timed out after {timeout} seconds",
        }}
"""


def globus_compute_register_shell_command(
    command: Annotated[
        str,
        Field(
            description=(
                "The shell command string, which may contain variables to be replaced with"
                " args and kwargs provided in each submit call (e.g.`echo {} --foo {foo}`)."
            )
        ),
    ],
    timeout: Annotated[
        float | None,
        Field(default=None, description="Maximum execution time in seconds."),
    ],
    description: Annotated[
        str | None,
        Field(default=None, description="An optional description of the shell command"),
    ],
    public: Annotated[
        bool,
        Field(
            description="Indicates whether the shell command can be used by others",
            default=False,
        ),
    ],
    ctx: Context[ServerSession, GlobusContext],
) -> ComputeFunctionRegisterResponse:
    """Register a shell command function with Globus Compute.

    Use globus_compute_submit_task to run the registered shell command on an endpoint.
    """
    client = get_compute_client(ctx)

    function_name = "run_shell_command"
    source = _SHELL_FUNCTION_TEMPLATE.format(
        function_name=function_name, command=command, timeout=timeout
    )

    try:
        function_id = client.register_source_code(
            source=source,
            function_name=function_name,
            description=description,
            public=public,
        )
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to register shell command: {e}") from e

    return ComputeFunctionRegisterResponse(function_id=function_id)


def globus_compute_submit_task(
    endpoint_id: Annotated[
        str, Field(description="ID of the endpoint that will execute the function")
    ],
    function_id: Annotated[str, Field(description="ID of the function")],
    function_args: Annotated[
        tuple[Any, ...] | None,
        Field(description="Positional arguments for the function"),
    ],
    function_kwargs: Annotated[
        dict[str, Any] | None, Field(description="Keyword arguments for the function")
    ],
    ctx: Context[ServerSession, GlobusContext],
) -> ComputeSubmitResponse:
    """Submit a function execution task to a Globus Compute endpoint.

    Use globus_compute_get_task_status to monitor progress and retrieve results.
    """
    client = get_compute_client(ctx)

    batch = client.create_batch(result_serializers=[validate_strategylike(JSONData).import_path])
    batch.add(function_id, function_args, function_kwargs)

    try:
        res = client.batch_run(endpoint_id, batch)
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to submit task: {e}") from e

    task_id = res["tasks"][function_id][0]
    return ComputeSubmitResponse(task_id=task_id)


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


ALL_COMPUTE_TOOLS: list[Callable[..., Any]] = [
    # globus_compute_list_endpoints,
    # globus_compute_register_python_function,
    # globus_compute_register_shell_command,
    # globus_compute_submit_task,
    globus_compute_get_task_status,
]
