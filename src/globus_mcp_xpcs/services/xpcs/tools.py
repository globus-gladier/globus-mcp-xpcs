import logging
from collections.abc import Callable
from typing import Annotated, Any, cast

import globus_sdk
from globus_compute_sdk import Executor
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from pydantic import Field

from globus_mcp_xpcs import config
from globus_mcp_xpcs.context import GlobusContext
from globus_mcp_xpcs.services.compute.client import get_compute_client
from globus_mcp_xpcs.services.compute.tools import register_function
from globus_mcp_xpcs.services.xpcs.schemas import (
    XPCSBoostCorrSubmitResponse,
)

log = logging.getLogger(__name__)


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
    if "output" not in boost_corr:
        boost_corr["output"] = str(pathlib.Path(raw).parent)
    boost_corr["raw"] = raw
    boost_corr["qmap"] = qmap

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

    raw_path = pathlib.Path(raw)
    result_stem = f"{raw_path.stem}_results"
    output_file = None
    for candidate in sorted(output_dir.iterdir()):
        if candidate.is_file() and candidate.stem == result_stem:
            output_file = str(candidate)
            break

    result = {
        "result": "SUCCEEDED" if completed.returncode == 0 else "FAILED",
        "returncode": completed.returncode,
        "execution_time_seconds": execution_time_seconds,
        "output_file": output_file,
    }
    if flow_debug:
        result["stdout"] = completed.stdout[-1000:]
        result["stderr"] = completed.stderr[-2000:]
    return result


def run_xpcs_boost_corr(
    raw_files: Annotated[
        list[str],
        Field(
            min_length=1,
            description="Raw detector input files for boost corr. Each file must be on the "
            "compute endpoint filesystem and under the configured allowed basepath for the "
            "endpoint.",
        ),
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
        Field(
            default=False,
            description="Enable verbose debug mode for boost corr",
        ),
    ] = False,
    compute_endpoint_id: Annotated[
        str,
        Field(description="Compute endpoint ID where boost_corr should run"),
    ] = config.DEFAULT_COMPUTE_ENDPOINT,
) -> XPCSBoostCorrSubmitResponse:
    """Run Boost Corr on one raw dataset with the given qmap parateter file.

    This tool submits one compute job and returns immediately with the submitted task_id and
    task_group_id. Use globus_compute_get_task_status with
    task UUIDs from your client-side tracking to monitor progress and retrieve completed task
    results, including output_file.

    Make sure source data is on the compute endpoint filesystem before running boost_corr.
    The boost_corr executable will not transfer data for you.

    A Boost Corr dataset consists of a data file and a metadata file within a directory.
    Never specify the metadata file as the raw input, only the data file. The metadata file is
    automatically detected by the boost_corr executable, typically has a filename ending in
    "_metadata.hdf" There are multiple raw data types that boost corr supports::

        1. eiger4m/lambda2m/rigaku(slow mode) .h5
        2. lambda750k, legacy .imm file. we no longer use it at the beamline.
        3. rigaku500k (fast mode), one .bin file
        4. rigaku3m (fast mode), .bin.xxx file, like .bin.000, .bin.001, etc. Always choose
            the first .bin.000 file as raw input. The boost_corr executable will automatically
            detect the rest of the .bin.xxx files in the same directory.

    Boost corr writes its outputs into the directory named by extra_boost_corr_params["output"].
    If output is not set, this tool defaults to the same directory as the raw file.
    The completed task result
    reports output_file when it finds a file in that output directory whose stem matches the
    raw filename plus "_results". For example:

    Cb0058_D100_a0011_f2000000_r00001_t76ns.hdf

    outputs:

    Cb0058_D100_a0011_f2000000_r00001_t76ns_results.hdf

    A source dataset raw file may look like this:

    /8IDI/2025-2/tempus202507-merge/data/Ea0234_EP5_a0115_f2000000/
    Ea0234_EP5_a0115_f2000000_r00001_t76ns/
    Ea0234_EP5_a0115_f2000000_r00001_t76ns.bin

    Where:

    * 2025-2 is the run cycle, in YYYY-N format, where in is the trimester of the year
    * tempus202507-merge is the experiment,
    * Ea0234_EP5_a0115_f2000000 is the experiment subdirectory
    * Ea0234_EP5_a0115_f2000000_r00001_t76ns is the dataset
    * Ea0234_EP5_a0115_f2000000_r00001_t76ns.bin is the raw data file.

    There may be additional subdirectories in the path, but datasets should always contain the
    raw data file and the metadata file.

    Always verify that the dataset is on the compute endpoint filesystem, and transfer it from the
    source collection to the compute endpoint filesystem before running boost_corr. The boost_corr
    executable will not transfer data for you.

    For example, you cannot run boost corr on data in /8IDI/2025-2/, you must transfer it to eagle
    first.
    """
    client = get_compute_client(ctx)
    endpoint_config = config.get_endpoint(compute_endpoint_id)
    if endpoint_config is None:
        raise ToolError(f"Unknown compute endpoint ID '{compute_endpoint_id}'")

    for raw in raw_files:
        if not config.compute_path_in_allowed_basepaths(compute_endpoint_id, raw):
            raise ToolError(
                f"Raw file '{raw}' is not under an allowed basepath for compute endpoint "
                f"'{compute_endpoint_id}'"
            )

    batch = client.create_batch(user_endpoint_config=endpoint_config["config"])
    function_id = register_function(_compute_run_boost_corr_executable, client)
    for raw in raw_files:
        batch.add(
            function_id,
            (),
            {
                "raw": raw,
                "qmap": qmap,
                "extra_boost_corr_params": extra_boost_corr_params,
                "flow_debug": flow_debug,
            },
        )

    try:
        res = client.batch_run(compute_endpoint_id, batch)
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to submit task: {e}") from e

    task_ids = res.get("tasks", {}).get(function_id)
    if not task_ids:
        raise ToolError(f"Failed to retrieve task IDs for function '{function_id}'")

    task_group_id = res.get("task_group_id")
    if not task_group_id:
        raise ToolError(f"Failed to retrieve task_group_id for function '{function_id}'")

    return XPCSBoostCorrSubmitResponse(
        task_ids=task_ids,
        task_group_id=task_group_id,
    )


def _get_boost_corr_metadata(
    corr_results: str,
) -> dict[str, Any]:
    """
    Takes the corr results file and generates metadata and plots at a given location. Optionally
    allows for specifying extra metadata if desired.

    Generates a handful of files under the target dir, like: ``webplot_target_dir/corr_results/``
    These files consist of several plots plus a metadata.json file. This metadata.json file is
    updated with data within webplot_extra_metadata.

    :param corr_results: The output file generated by Corr. Raises an exception if this file
    does not exist or if the HDF file is bad.
    :param webplot_target_dir: Specifies where to generate the plots/metadata. Typically under
    a local resources/ directory
    :param webplot_extra_metadata: Optional -- any additional metadata to include in the
    metadata file.

    """
    import time
    from datetime import datetime

    import numpy as np  # type: ignore[import-not-found]
    from xpcs_webplot import __version__ as webplot_version  # type: ignore[import-not-found]
    from xpcs_webplot.plot_images import XF  # type: ignore[import-not-found]

    def numpy_to_python(obj: Any) -> Any:
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, dict):
            return {k: numpy_to_python(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [numpy_to_python(v) for v in obj]
        return obj

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
    metadata = {k: numpy_to_python(v) for k, v in xf.get_hdf_info().items()}
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
    ] = config.DEFAULT_COMPUTE_ENDPOINT,
) -> dict[str, Any]:
    """Get metadata and plots from a boost_corr output HDF file."""
    try:
        client = get_compute_client(ctx)
        endpoint_config = config.get_endpoint(compute_endpoint_id)
        if endpoint_config is None:
            raise ToolError(f"Unknown compute endpoint ID '{compute_endpoint_id}'")

        with Executor(
            endpoint_id=compute_endpoint_id,
            client=client,
            user_endpoint_config=endpoint_config["config"],
        ) as executor:
            future = executor.submit(  # type: ignore[no-untyped-call]
                _get_boost_corr_metadata,
                corr_results=corr_results,
            )
            return cast(dict[str, Any], future.result())
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

        import h5py  # type: ignore[import-not-found]

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
            all_attrs["/"] = {str(k): _to_jsonable(v) for k, v in h5f.attrs.items()}

            def _collect_attrs(name: str, obj: Any) -> None:
                key = f"/{name}" if not str(name).startswith("/") else str(name)
                all_attrs[key] = {str(k): _to_jsonable(v) for k, v in obj.attrs.items()}

            h5f.visititems(_collect_attrs)

        execution_time_seconds = round(time.time() - metadata_fetch_start, 2)
        return {
            "input_hdf": corr_results,
            "execution_time_seconds": execution_time_seconds,
            "metadata": {"hdf5_attributes": all_attrs},
        }

    try:
        client = get_compute_client(ctx)
        with Executor(endpoint_id=config.DEFAULT_COMPUTE_ENDPOINT, client=client) as executor:
            future = executor.submit(  # type: ignore[no-untyped-call]
                _get_generic_metadata,
                corr_results=corr_results,
            )
            return cast(dict[str, Any], future.result())
    except Exception as e:
        raise ToolError(f"Failed to run boost_corr compute function: {e}") from e


ALL_XPCS_TOOLS: list[Callable[..., Any]] = [
    run_xpcs_boost_corr,
    get_boost_corr_metadata,
    get_generic_metadata,
    # xpcs_ls_source,
    # xpcs_transfer_data,
    # globus_transfer_get_task_events,
]
