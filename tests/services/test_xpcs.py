from unittest.mock import MagicMock, Mock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from globus_mcp.services.xpcs.tools import (
    _compute_run_boost_corr_executable,
    _wait_for_task_ids,
    run_xpcs_boost_corr,
)


def test_run_xpcs_boost_corr_submits_one_job_per_raw_file(mock_ctx: Mock):
    mock_client = Mock()
    mock_executor = MagicMock()
    mock_executor.__enter__.return_value = mock_executor
    mock_executor.submit.side_effect = [
        Mock(task_id="task-1"),
        Mock(task_id="task-2"),
    ]

    with (
        patch("globus_mcp.services.xpcs.tools.get_compute_client", return_value=mock_client),
        patch(
            "globus_mcp.services.xpcs.tools.config.get_endpoint",
            return_value={"config": {"queue": "debug"}},
        ),
        patch("globus_mcp.services.xpcs.tools.Executor", return_value=mock_executor),
    ):
        res = run_xpcs_boost_corr(
            raw=["/path/to/raw-1.h5", "/path/to/raw-2.h5"],
            qmap="/path/to/qmap.hdf",
            ctx=mock_ctx,
        )

    assert res.task_uuids == ["task-1", "task-2"]
    assert mock_executor.submit.call_count == 2
    mock_executor.submit.assert_any_call(
        _compute_run_boost_corr_executable,
        raw="/path/to/raw-1.h5",
        qmap="/path/to/qmap.hdf",
        extra_boost_corr_params=None,
        flow_debug=False,
    )
    mock_executor.submit.assert_any_call(
        _compute_run_boost_corr_executable,
        raw="/path/to/raw-2.h5",
        qmap="/path/to/qmap.hdf",
        extra_boost_corr_params=None,
        flow_debug=False,
    )


def test_wait_for_task_ids_waits_for_delayed_ids():
    class DelayedFuture:
        def __init__(self, values: list[str | None]):
            self._values = values
            self._index = 0

        @property
        def task_id(self) -> str | None:
            value = self._values[min(self._index, len(self._values) - 1)]
            self._index += 1
            return value

    futures = [
        DelayedFuture([None, "task-1"]),
        DelayedFuture([None, None, "task-2"]),
    ]

    with patch("globus_mcp.services.xpcs.tools.time.sleep", return_value=None):
        task_ids = _wait_for_task_ids(futures, timeout_seconds=1.0, polling_interval_seconds=0.001)

    assert task_ids == ["task-1", "task-2"]


def test_wait_for_task_ids_timeout():
    future = Mock(task_id=None)

    with pytest.raises(ToolError, match="Timed out waiting for Globus Compute task IDs"):
        _wait_for_task_ids([future], timeout_seconds=0.01, polling_interval_seconds=0.001)


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
    output_dir = tmp_path / "boost_corr_output_claude_test"
    output_dir.mkdir()
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
