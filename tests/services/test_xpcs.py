from unittest.mock import Mock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from globus_mcp_xpcs.services.xpcs.tools import (
    _compute_run_boost_corr_executable,
    run_xpcs_boost_corr,
)


def test_run_xpcs_boost_corr_submits_one_job(mock_ctx: Mock):
    mock_client = Mock()
    mock_batch = Mock()
    mock_client.create_batch.return_value = mock_batch
    mock_client.batch_run.return_value = {
        "tasks": {"function-1": ["task-1"]},
        "task_group_id": "group-1",
    }
    valid_raw = "/eagle/APSDataProcessing/aps8idi/xpcs_staging/agentic-testing/raw-1.h5"

    with (
        patch("globus_mcp_xpcs.services.xpcs.tools.get_compute_client", return_value=mock_client),
        patch(
            "globus_mcp_xpcs.services.xpcs.tools.config.get_endpoint",
            return_value={
                "config": {"queue": "debug"},
            },
        ),
        patch(
            "globus_mcp_xpcs.services.xpcs.tools.config.compute_path_in_allowed_basepaths",
            return_value=True,
        ),
        patch("globus_mcp_xpcs.services.xpcs.tools.register_function", return_value="function-1"),
    ):
        res = run_xpcs_boost_corr(
            raw_files=[valid_raw],
            qmap="/path/to/qmap.hdf",
            ctx=mock_ctx,
            compute_endpoint_id="endpoint-1",
        )

    assert res.task_ids == ["task-1"]
    assert res.task_group_id == "group-1"
    mock_batch.add.assert_called_once()


def test_run_xpcs_boost_corr_rejects_path_not_in_allowed_basepaths(mock_ctx: Mock):
    mock_client = Mock()

    with (
        patch("globus_mcp_xpcs.services.xpcs.tools.get_compute_client", return_value=mock_client),
        patch(
            "globus_mcp_xpcs.services.xpcs.tools.config.get_endpoint",
            return_value={"config": {"queue": "debug"}},
        ),
        patch(
            "globus_mcp_xpcs.services.xpcs.tools.config.compute_path_in_allowed_basepaths",
            return_value=False,
        ),
    ):
        with pytest.raises(ToolError, match="not under an allowed basepath"):
            run_xpcs_boost_corr(
                raw_files=["/tmp/other/raw-1.h5"],
                qmap="/path/to/qmap.hdf",
                ctx=mock_ctx,
                compute_endpoint_id="endpoint-1",
            )


def test_run_xpcs_boost_corr_missing_task_id_raises(mock_ctx: Mock):
    mock_client = Mock()
    mock_batch = Mock()
    mock_client.create_batch.return_value = mock_batch
    mock_client.batch_run.return_value = {"tasks": {"function-1": None}, "task_group_id": "group-1"}

    with (
        patch("globus_mcp_xpcs.services.xpcs.tools.get_compute_client", return_value=mock_client),
        patch(
            "globus_mcp_xpcs.services.xpcs.tools.config.get_endpoint",
            return_value={
                "config": {"queue": "debug"},
            },
        ),
        patch(
            "globus_mcp_xpcs.services.xpcs.tools.config.compute_path_in_allowed_basepaths",
            return_value=True,
        ),
        patch("globus_mcp_xpcs.services.xpcs.tools.register_function", return_value="function-1"),
    ):
        with pytest.raises(ToolError, match="Failed to retrieve task IDs"):
            run_xpcs_boost_corr(
                raw_files=[
                    "/eagle/APSDataProcessing/aps8idi/xpcs_staging/agentic-testing/raw-1.h5"
                ],
                qmap="/path/to/qmap.hdf",
                ctx=mock_ctx,
                compute_endpoint_id="endpoint-1",
            )


def test_run_xpcs_boost_corr_missing_task_group_id_raises(mock_ctx: Mock):
    mock_client = Mock()
    mock_batch = Mock()
    mock_client.create_batch.return_value = mock_batch
    mock_client.batch_run.return_value = {
        "tasks": {"function-1": ["task-1"]},
        "task_group_id": None,
    }

    with (
        patch("globus_mcp_xpcs.services.xpcs.tools.get_compute_client", return_value=mock_client),
        patch(
            "globus_mcp_xpcs.services.xpcs.tools.config.get_endpoint",
            return_value={
                "config": {"queue": "debug"},
            },
        ),
        patch(
            "globus_mcp_xpcs.services.xpcs.tools.config.compute_path_in_allowed_basepaths",
            return_value=True,
        ),
        patch("globus_mcp_xpcs.services.xpcs.tools.register_function", return_value="function-1"),
    ):
        with pytest.raises(ToolError, match="Failed to retrieve task_group_id"):
            run_xpcs_boost_corr(
                raw_files=[
                    "/eagle/APSDataProcessing/aps8idi/xpcs_staging/agentic-testing/raw-1.h5"
                ],
                qmap="/path/to/qmap.hdf",
                ctx=mock_ctx,
                compute_endpoint_id="endpoint-1",
            )


def test_compute_run_boost_corr_executable_returns_output_file(tmp_path):
    raw_file = tmp_path / "sample.h5"
    raw_file.write_text("raw")
    output_dir = tmp_path / "boost_output"
    output_dir.mkdir()
    result_file = output_dir / "sample_results.hdf"
    result_file.write_text("result")

    completed = Mock(returncode=0, stdout="ok", stderr="")

    with patch("subprocess.run", return_value=completed):
        result = _compute_run_boost_corr_executable(
            raw=str(raw_file),
            qmap="/path/to/qmap.hdf",
            extra_boost_corr_params={"output": str(output_dir)},
            flow_debug=False,
        )

    assert result["output_file"] == str(result_file)


def test_compute_run_boost_corr_executable_uses_default_output_directory(tmp_path):
    raw_file = tmp_path / "sample.h5"
    raw_file.write_text("raw")
    output_dir = tmp_path
    result_file = output_dir / "sample_results.hdf"
    result_file.write_text("result")

    completed = Mock(returncode=0, stdout="ok", stderr="")

    with patch("subprocess.run", return_value=completed):
        result = _compute_run_boost_corr_executable(
            raw=str(raw_file),
            qmap="/path/to/qmap.hdf",
            extra_boost_corr_params=None,
            flow_debug=False,
        )

    assert result["output_file"] == str(result_file)
