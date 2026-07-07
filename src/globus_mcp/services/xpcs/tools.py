from collections.abc import Callable
from typing import Annotated, Any

from globus_compute_sdk import Executor

from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from pydantic import Field

from globus_mcp.context import GlobusContext
from globus_mcp import config
from globus_mcp.services.compute.client import get_compute_client
from globus_mcp.services.xpcs.schemas import (
    XPCSBoostCorrResult,
    CollectionInfo,
    CollectionBasepath,
    ComputeEndpointInfo,
    ComputeEndpointBasepath,
)


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
    compute_endpoint_id: Annotated[
        str,
        Field(description="Compute endpoint ID where boost_corr should run"),
    ] = config.DEFAULT_COMPUTE_ENDPOINT,
) -> XPCSBoostCorrResult:
    """Submit a compute function that executes boost_corr directly.

    This sends a Python compute function to the selected endpoint, where it invokes
    the boost_corr executable with raw/qmap plus any extra boost_corr parameters.
    """
    try:
        client = get_compute_client(ctx)
        with Executor(endpoint_id=compute_endpoint_id, client=client) as executor:
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


def _get_boost_corr_metadata(
    corr_results: str,
):
    """
    Takes the corr results file and generates metadata and plots at a given location. Optionally
    allows for specifying extra metadata if desired.

    Generates a handful of files under the target dir, like: ``webplot_target_dir/corr_results/``
    These files consist of several plots plus a metadata.json file. This metadata.json file is updated
    with data within webplot_extra_metadata.

    :param corr_results: The output file generated by Corr. Raises an exception if this file does not
    exist or if the HDF file is bad.
    :param webplot_target_dir: Specifies where to generate the plots/metadata. Typically under a local
                               resources/ directory
    :param webplot_extra_metadata: Optional -- any additional metadata to include in the metadata file.
    
    """
    import os
    import json
    import time
    import pathlib
    from datetime import datetime
    from xpcs_webplot.plot_images import hdf2web_safe, XF, NpEncoder
    from xpcs_webplot import __version__ as webplot_version

    metadata_fetch_start = time.time()
    # webplot_output = hdf2web_safe(
    #     corr_results, target_dir=webplot_target_dir, image_only=True, overwrite=True
    # )
    # if webplot_output is None:
    #     raise Exception(
    #         "Plots failed to generate This is likely a problem with a bad input HDF "
    #         f"({corr_results})"
    #     )

    xf = XF(corr_results)
    metadata = xf.get_hdf_info()
    metadata["analysis_type"] = xf.atype
    metadata["start_time"] = xf.start_time
    metadata["plot_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # tools = webplot_extra_metadata.get('tools', [])
    # tools += corr_timing_output.get("tools", [])

    execution_time_seconds = round(time.time() - metadata_fetch_start, 2)
    tools = [
        {
            "name": "xpcs_webplot",
            "tool_version": str(webplot_version),
            "execution_time_seconds": execution_time_seconds,
            "device": "cpu",
            "source": "https://github.com/AZjk/xpcs_webplot",
        }
    ]
    metadata["tools"] = tools
    # metadata.update(webplot_extra_metadata or {})
    # save_dir = (
    #     pathlib.Path(webplot_target_dir)
    #     / f"{pathlib.Path(corr_results).stem}"
    #     / "metadata.json"
    # )
    # with open(save_dir, "w") as f:
    #     json.dump({"project_metadata": metadata}, f, indent=4, cls=NpEncoder)

    return {
        # "images": [
        #     img for img in os.listdir(webplot_target_dir) if img.endswith(".png")
        # ],
        # "images_directory": str(webplot_target_dir),
        "input_hdf": corr_results,
        # "webplot_output": webplot_output,
        "execution_time_seconds": execution_time_seconds,
        "metadata": metadata,
    }


def get_boost_corr_metadata(
    corr_results: Annotated[
        str,
        Field(description="Path to the boost_corr output HDF file"),
    ],
    ctx: Context[ServerSession, GlobusContext],
    compute_endpoint_id: Annotated[
        str,
        Field(description="Compute endpoint ID where boost_corr metadata should be generated"),
    ] = config.DEFAULT_COMPUTE_ENDPOINT
) -> dict[str, Any]:
    """Get metadata and plots from a boost_corr output HDF file."""
    try:
        client = get_compute_client(ctx)
        with Executor(endpoint_id=compute_endpoint_id, client=client) as executor:
            future = executor.submit(
                _get_boost_corr_metadata,
                corr_results=corr_results,
            )
            return XPCSBoostCorrResult.model_validate(future.result())
    except Exception as e:
        raise ToolError(f"Failed to run boost_corr compute function: {e}") from e


def get_generic_metadata(
    corr_results: Annotated[
        str,
        Field(description="Path to the boost_corr output HDF file"),
    ],
    ctx: Context[ServerSession, GlobusContext],
) -> dict[str, Any]:
    """Get metadata from a boost_corr output HDF file."""
    def _get_generic_metadata(corr_results: str) -> dict[str, Any]:
        import time

        import h5py

        def _to_jsonable(value: Any) -> Any:
            # Handle common h5py/numpy scalar wrappers
            if hasattr(value, "item"):
                try:
                    return _to_jsonable(value.item())
                except Exception:
                    pass

            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace")

            if isinstance(value, (str, int, float, bool)) or value is None:
                return value

            if isinstance(value, complex):
                return {"real": value.real, "imag": value.imag}

            if isinstance(value, dict):
                return {str(k): _to_jsonable(v) for k, v in value.items()}

            if isinstance(value, (list, tuple, set)):
                return [_to_jsonable(v) for v in value]

            if hasattr(value, "tolist"):
                try:
                    return _to_jsonable(value.tolist())
                except Exception:
                    pass

            # Final fallback for unsupported objects
            return str(value)

        metadata_fetch_start = time.time()
        all_attrs: dict[str, dict[str, Any]] = {}

        with h5py.File(corr_results, "r") as h5f:
            # Root attributes
            all_attrs["/"] = {
                str(k): _to_jsonable(v) for k, v in h5f.attrs.items()
            }

            def _collect_attrs(name: str, obj: Any) -> None:
                key = f"/{name}" if not str(name).startswith("/") else str(name)
                all_attrs[key] = {
                    str(k): _to_jsonable(v) for k, v in obj.attrs.items()
                }

            h5f.visititems(_collect_attrs)

        execution_time_seconds = round(time.time() - metadata_fetch_start, 2)
        return {
            "input_hdf": corr_results,
            "execution_time_seconds": execution_time_seconds,
            "metadata": {"hdf5_attributes": all_attrs},
        }

    try:
        client = get_compute_client(ctx)
        with Executor(endpoint_id=config.GLOBUS_COMPUTE_ENDPOINT, client=client) as executor:
            future = executor.submit(
                _get_generic_metadata,
                corr_results=corr_results,
            )
            return future.result()
    except Exception as e:
        raise ToolError(f"Failed to run boost_corr compute function: {e}") from e

def list_xpcs_collections() -> list[CollectionInfo]:
    """List the configured XPCS Globus Transfer collections and their allowed filesystem paths/permissions."""
    return [
        CollectionInfo(
            uuid=col["uuid"],
            display_name=col["display_name"],
            description=col["description"],
            collection_basepath=col["collection_basepath"],
            allowed_basepaths=[
                CollectionBasepath(
                    path=bp["path"],
                    permissions=bp["permissions"],
                )
                for bp in col.get("allowed_basepaths", [])
            ],
        )
        for col in config.COLLECTIONS
    ]


def list_xpcs_compute_endpoints() -> list[ComputeEndpointInfo]:
    """List the configured XPCS compute endpoints and their allowed filesystem paths/permissions."""
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


ALL_XPCS_TOOLS: list[Callable[..., Any]] = [
    list_xpcs_collections,
    list_xpcs_compute_endpoints,
    run_xpcs_boost_corr,
    get_boost_corr_metadata,
    get_generic_metadata,
    # xpcs_ls_source,
    # xpcs_transfer_data,
    # globus_transfer_get_task_events,
]
