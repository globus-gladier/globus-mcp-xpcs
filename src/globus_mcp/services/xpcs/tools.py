from collections.abc import Callable
from typing import Annotated, Any
import pathlib

import globus_sdk
from globus_compute_sdk import Executor

from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from pydantic import Field

from globus_mcp.context import GlobusContext
from globus_mcp.services.transfer.client import get_transfer_client
from globus_mcp.services.compute.client import get_compute_client
from globus_mcp.services.transfer.schemas import TransferSubmitResponse

from globus_mcp.services.xpcs import config
from globus_mcp.services.xpcs.schemas import XPCSBoostCorrResult


def _compute_run_boost_corr_executable(
    raw: str,
    qmap: str,
    extra_boost_corr_params: dict[str, Any] | None = None,
    flow_debug: bool = False,
) -> dict[str, Any]:
    """Compute function that executes the boost_corr CLI directly."""
    import json
    import pathlib
    import subprocess
    import time

    boost_corr = dict(extra_boost_corr_params or {})
    boost_corr["raw"] = raw
    boost_corr["qmap"] = qmap

    if "output" not in boost_corr:
        boost_corr["output"] = str(
            pathlib.Path(raw).parent / "boost_corr_output_claude_test"
        )

    output_dir = pathlib.Path(boost_corr["output"])
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "boost_corr",
        "-r",
        boost_corr["raw"],
        "-q",
        boost_corr["qmap"],
        "-o",
        boost_corr["output"],
        "-i",
        str(boost_corr.get("gpu_id", 0)),
        "-s",
        str(boost_corr.get("smooth", "sqmap")),
        "-b",
        str(boost_corr.get("begin_frame", 0)),
        "-e",
        str(boost_corr.get("end_frame", -1)),
        "-f",
        str(boost_corr.get("stride_frame", 1)),
        "-a",
        str(boost_corr.get("avg_frame", 1)),
        "-t",
        str(boost_corr.get("type", "Multitau")),
        "-d",
        str(boost_corr.get("dq_selection", "all")),
    ]

    if boost_corr.get("save_g2", False):
        cmd.append("-G")
    if boost_corr.get("overwrite", False):
        cmd.append("-w")
    if boost_corr.get("verbose", False):
        cmd.append("-v")

    start_time = time.time()
    completed = subprocess.run(cmd, capture_output=True, text=True)
    execution_time_seconds = round(time.time() - start_time, 2)

    (output_dir / "boost_corr.log").write_text(completed.stdout)
    (output_dir / "boost_corr_err.log").write_text(completed.stderr)
    (output_dir / "corr_metadata_output.json").write_text(
        json.dumps(
            {
                "boost_corr": boost_corr,
                "execution_time_seconds": execution_time_seconds,
                "returncode": completed.returncode,
            },
            indent=2,
        )
    )

    result = {
        "result": "SUCCEEDED" if completed.returncode == 0 else "FAILED",
        "returncode": completed.returncode,
        "execution_time_seconds": execution_time_seconds,
    }
    if flow_debug:
        result["stdout"] = completed.stdout[-1000:]
        result["stderr"] = completed.stderr[-2000:]
    return result


def run_xpcs_boost_corr(
    raw: Annotated[
        str,
        Field(description="Path to the raw detector input file for boost corr"),
    ],
    qmap: Annotated[
        str,
        Field(description="Path to the qmap file for boost corr"),
    ],
    ctx: Context[ServerSession, GlobusContext],
    extra_boost_corr_params: Annotated[
        dict[str, Any] | None,
        Field(
            default=None,
            description=(
                "Additional boost corr parameters. Include required fields such as "
                "'output' and any optional algorithm/runtime parameters."
            ),
        ),
    ] = None,
    flow_debug: Annotated[
        bool,
        Field(default=False, description="Enable verbose debug mode for boost corr"),
    ] = False,
    endpoint_id: Annotated[
        str,
        Field(description="Compute endpoint ID where boost_corr should run"),
    ] = "f8f4692a-0ab7-40d0-b256-ba5b82b5e2ec",
) -> XPCSBoostCorrResult:
    """Submit a compute function that executes boost_corr directly.

    This sends a Python compute function to the selected endpoint, where it invokes
    the boost_corr executable with raw/qmap plus any extra boost_corr parameters.
    """
    try:
        client = get_compute_client(ctx)
        with Executor(endpoint_id=endpoint_id, client=client) as executor:
            future = executor.submit(
                _compute_run_boost_corr_executable,
                raw=raw,
                qmap=qmap,
                extra_boost_corr_params=extra_boost_corr_params,
                flow_debug=flow_debug,
            )
            return XPCSBoostCorrResult.model_validate(future.result())
    except Exception as e:
        raise ToolError(f"Failed to run boost_corr compute function: {e}") from e


def xpcs_ls_source(
    source_path: Annotated[str, Field(description="Source file or directory path")],
    ctx: Context[ServerSession, GlobusContext],
) -> list[dict[str, Any]]:
    """List files in a source directory on the Globus endpoint.

    Currently limited to "/8IDI/2025-2/tempus202507-merge/data/converted/"

    Args:
        source_path (str): The source file or directory path to list.
        ctx (Context[ServerSession, GlobusContext]): The context containing session and Globus context.

    Returns:
        list[dict[str, Any]]: A list of dictionaries representing the files in the source directory.
    """
    if not source_path.startswith("/8IDI/2025-2/tempus202507-merge/data/converted/"):
        raise ToolError(
            f"Source path '{source_path}' is not allowed. Must start with '/8IDI/2025-2/tempus202507-merge/data/converted/'."
        )

    client = get_transfer_client(ctx)
    try:
        res = client.operation_ls(
            endpoint_id=config.GLOBUS_ENDPOINT_VOYAGER,
            path=source_path,
        )
        return res.data["DATA"]
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to list source directory: {e}") from e


def xpcs_transfer_data(
    transfer_items: Annotated[
        list[dict[str, Any]],
        Field(
            description=(
                "List of transfer items. Each item must include 'source_path' and "
                "'destination_path', and may include optional 'recursive'."
            )
        ),
    ],
    ctx: Context[ServerSession, GlobusContext],
) -> TransferSubmitResponse:
    """Submit a Globus Transfer task with multiple source/destination pairs.

    Each transfer item is added to a single task.
    Prepends the destination path with a staging subdirectory: `/xpcs_staging/agentic-testing`.
    """
    client = get_transfer_client(ctx)
    staging_subdir = pathlib.Path("/xpcs_staging/agentic-testing")

    data = globus_sdk.TransferData(
        source_endpoint=config.GLOBUS_ENDPOINT_VOYAGER,
        destination_endpoint=config.GLOBUS_ENDPOINT_EAGLE_APS_DATA_PROCESSING,
        label="XPCS MCP Transfer Task",
    )

    if not transfer_items:
        raise ToolError(
            "transfer_items must contain at least one source/destination pair"
        )

    for idx, item in enumerate(transfer_items):
        source_path = item.get("source_path")
        destination_path = item.get("destination_path")
        if not source_path or not destination_path:
            raise ToolError(
                f"transfer_items[{idx}] must include 'source_path' and 'destination_path'"
            )

        item_recursive = bool(item.get("recursive", False))
        destination_path = str(
            staging_subdir / pathlib.Path(str(destination_path).lstrip("/"))
        )
        data.add_item(
            source_path=str(source_path),
            destination_path=destination_path,
            recursive=item_recursive,
        )

    try:
        res = client.submit_transfer(data)
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to submit transfer: {e}") from e

    return TransferSubmitResponse(task_id=res.data["task_id"])


ALL_XPCS_TOOLS: list[Callable[..., Any]] = [
    run_xpcs_boost_corr,
    xpcs_ls_source,
    xpcs_transfer_data,
]
