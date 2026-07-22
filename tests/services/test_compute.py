import random
import sys
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from globus_compute_sdk import Client
from globus_compute_sdk.sdk.batch import Batch
from globus_compute_sdk.serialize import JSONData, PureSourceTextInspect
from globus_compute_sdk.serialize.facade import validate_strategylike
from globus_sdk import GlobusAPIError
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from globus_mcp.context import GlobusContext
from globus_mcp.server import service_registry
from globus_mcp.services.compute.client import get_compute_client
from globus_mcp.services.compute.registry import register_compute
from globus_mcp.services.compute.tools import (
    _SHELL_FUNCTION_TEMPLATE,
    ALL_COMPUTE_TOOLS,
    globus_compute_get_task_status,
    globus_compute_list_endpoints,
    globus_compute_register_python_function,
    globus_compute_register_shell_command,
    globus_compute_submit_task,
)
from tests.utils import random_string


@pytest.fixture
def mock_client():
    with patch("globus_mcp.services.compute.tools.get_compute_client") as mock_get_client:
        mc = Mock(spec=Client)
        mc.fx_serializer = Mock()
        mc._compute_web_client = Mock()
        mock_get_client.return_value = mc
        yield mc


def test_compute_in_service_registry():
    assert "compute" in service_registry
    assert service_registry["compute"] is register_compute


def test_register_compute():
    mcp = Mock(spec=FastMCP)
    register_compute(mcp)
    registered = [c[0][0] for c in mcp.add_tool.call_args_list]
    for tool in ALL_COMPUTE_TOOLS:
        assert tool in registered


def test_get_compute_client(mock_ctx: Mock):
    globus_ctx: GlobusContext = mock_ctx.request_context.lifespan_context
    assert globus_ctx.compute_client is None, "Ensure setup"

    client = get_compute_client(mock_ctx)
    assert globus_ctx.compute_client is client
    assert isinstance(client, Client)
    assert client.app is globus_ctx.app
    assert isinstance(client.fx_serializer.code_serializer, PureSourceTextInspect)
    assert isinstance(client.fx_serializer.data_serializer, JSONData)

    client_2 = get_compute_client(mock_ctx)
    assert client_2 is client, "Client should be cached"


def test_globus_compute_list_endpoints(mock_ctx: Mock, mock_client: Mock):
    res_data = []
    for _ in range(random.randint(1, 10)):
        res_data.append(
            {
                "uuid": str(uuid.uuid4()),
                "name": random_string(),
                "display_name": random_string(),
                "owner": str(uuid.uuid4()),
            }
        )
    mock_client.get_endpoints.return_value = res_data

    res = globus_compute_list_endpoints(role="any", ctx=mock_ctx)

    mock_client.get_endpoints.assert_called_once_with(role="any")
    assert isinstance(res, list)
    for idx, ep in enumerate(res):
        ep_data = res_data[idx]
        assert ep.endpoint_id == ep_data["uuid"]
        assert ep.name == ep_data["name"]
        assert ep.display_name == ep_data["display_name"]
        assert ep.owner_id == ep_data["owner"]


def test_globus_compute_list_endpoints_api_error(mock_ctx: Mock, mock_client: Mock):
    mock_client.get_endpoints.side_effect = GlobusAPIError(r=MagicMock())
    with pytest.raises(ToolError, match="Failed to get endpoints"):
        globus_compute_list_endpoints(role="any", ctx=mock_ctx)


def test_globus_compute_register_python_function(mock_ctx: Mock, mock_client: Mock):
    function_code = random_string()
    function_name = random_string()
    description = random_string()
    public = True
    function_id = str(uuid.uuid4())

    mock_client.register_source_code.return_value = function_id

    res = globus_compute_register_python_function(
        function_code=function_code,
        function_name=function_name,
        description=description,
        public=public,
        ctx=mock_ctx,
    )

    mock_client.register_source_code.assert_called_once_with(
        source=function_code,
        function_name=function_name,
        description=description,
        public=public,
    )
    assert res.function_id == function_id


def test_globus_compute_register_python_function_api_error(mock_ctx: Mock, mock_client: Mock):
    mock_client.register_source_code.side_effect = GlobusAPIError(r=MagicMock())
    with pytest.raises(ToolError, match="Failed to register Python function"):
        globus_compute_register_python_function(
            function_code=random_string(),
            function_name=random_string(),
            description=random_string(),
            public=True,
            ctx=mock_ctx,
        )


def test_shell_function_template():
    function_name = "run_shell_command"
    command = sys.executable + " -c \"print('{}', '{text}')\""
    source = _SHELL_FUNCTION_TEMPLATE.format(
        function_name=function_name,
        command=command,
        timeout=2,
    )

    namespace: dict[str, Any] = {}
    exec(source, namespace)

    arg1, arg2 = random_string(), random_string()
    res = namespace[function_name](arg1, text=arg2)

    assert res["returncode"] == 0
    assert res["stdout"].strip() == f"{arg1} {arg2}"
    assert res["stderr"] == ""


def test_shell_function_template_timeout():
    function_name = "run_shell_command"
    command = sys.executable + ' -c "import time; time.sleep(1)"'
    timeout = 0.1
    source = _SHELL_FUNCTION_TEMPLATE.format(
        function_name=function_name,
        command=command,
        timeout=timeout,
    )

    namespace: dict[str, Any] = {}
    exec(source, namespace)

    res = namespace[function_name]()

    assert res["returncode"] == -1
    assert res["stdout"].strip() == ""
    assert res["stderr"].strip() == f"Command timed out after {timeout} seconds"


def test_globus_compute_register_shell_command(mock_ctx: Mock, mock_client: Mock):
    function_name = "run_shell_command"
    command = f"echo {random_string()}"
    timeout = random.randint(1, 50)
    description = random_string()
    public = True
    function_id = str(uuid.uuid4())

    mock_client.register_source_code.return_value = function_id

    res = globus_compute_register_shell_command(
        command=command, timeout=timeout, description=description, public=public, ctx=mock_ctx
    )

    source = _SHELL_FUNCTION_TEMPLATE.format(
        function_name=function_name,
        command=command,
        timeout=timeout,
    )
    mock_client.register_source_code.assert_called_once_with(
        source=source,
        function_name=function_name,
        description=description,
        public=public,
    )
    assert res.function_id == function_id


def test_globus_compute_register_shell_command_api_error(mock_ctx: Mock, mock_client: Mock):
    mock_client.register_source_code.side_effect = GlobusAPIError(r=MagicMock())
    with pytest.raises(ToolError, match="Failed to register shell command"):
        globus_compute_register_shell_command(
            command=random_string(),
            timeout=random.randint(1, 60),
            description=random_string(),
            public=True,
            ctx=mock_ctx,
        )


def test_globus_compute_submit_task(mock_ctx: Mock, mock_client: Mock):
    endpoint_id = str(uuid.uuid4())
    function_id = str(uuid.uuid4())
    function_args = (random_string(), random.randint(1, 100))
    function_kwargs = {random_string(): random.randint(1, 100)}
    task_id = str(uuid.uuid4())

    mock_client.batch_run.return_value = {"tasks": {function_id: [task_id]}}
    mock_batch = Mock(spec=Batch)
    mock_client.create_batch.return_value = mock_batch

    res = globus_compute_submit_task(
        endpoint_id=endpoint_id,
        function_id=function_id,
        function_args=function_args,
        function_kwargs=function_kwargs,
        ctx=mock_ctx,
    )

    assert res.task_id == task_id
    mock_client.create_batch.assert_called_once_with(
        result_serializers=[validate_strategylike(JSONData).import_path]
    )
    mock_batch.add.assert_called_once_with(function_id, function_args, function_kwargs)
    mock_client.batch_run.assert_called_once_with(endpoint_id, mock_batch)


def test_globus_compute_submit_task_api_error(mock_ctx: Mock, mock_client: Mock):
    mock_client.batch_run.side_effect = GlobusAPIError(r=MagicMock())
    with pytest.raises(ToolError, match="Failed to submit task"):
        globus_compute_submit_task(
            endpoint_id=str(uuid.uuid4()),
            function_id=str(uuid.uuid4()),
            function_args=None,
            function_kwargs=None,
            ctx=mock_ctx,
        )


@pytest.mark.parametrize("result", [random_string(), None])
@pytest.mark.asyncio
async def test_globus_compute_get_task_status(
    result: str | None, mock_ctx: Mock, mock_client: Mock
):
    task_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    first_task_first_poll = {
        "task_id": task_ids[0],
        "status": "pending",
        "result": None,
        "exception": None,
    }
    first_task_second_poll = {
        "task_id": task_ids[0],
        "status": "success",
        "result": result,
        "exception": None,
    }
    second_task_first_poll = {
        "task_id": task_ids[1],
        "status": "success",
        "result": result,
        "exception": None,
    }

    mock_client._compute_web_client.v2.get_task.side_effect = [
        first_task_first_poll,
        second_task_first_poll,
        first_task_second_poll,
        second_task_first_poll,
    ]
    mock_client.fx_serializer.deserialize.return_value = result

    with patch(
        "globus_mcp.services.compute.tools.asyncio.sleep",
        new_callable=AsyncMock,
    ) as mock_sleep:
        res = await globus_compute_get_task_status(
            task_ids=task_ids,
            polling_interval=0.01,
            timeout_seconds=1,
            ctx=mock_ctx,
        )

    assert mock_client._compute_web_client.v2.get_task.call_count == 4
    assert mock_sleep.call_count == 1
    if result is not None:
        assert mock_client.fx_serializer.deserialize.call_count == 2
        mock_client.fx_serializer.deserialize.assert_any_call(result)
    else:
        mock_client.fx_serializer.deserialize.assert_not_called()

    assert res.total_tasks == 2
    assert res.completed_tasks == 2
    assert res.pending_tasks == 0
    assert [task.task_id for task in res.tasks] == task_ids


@pytest.mark.asyncio
async def test_globus_compute_get_task_status_api_error(mock_ctx: Mock, mock_client: Mock):
    mock_client._compute_web_client.v2.get_task.side_effect = GlobusAPIError(r=MagicMock())
    with pytest.raises(ToolError, match="Failed to get task status"):
        await globus_compute_get_task_status(task_ids=[str(uuid.uuid4())], ctx=mock_ctx)


@pytest.mark.asyncio
async def test_globus_compute_get_task_status_deserialization_error(
    mock_ctx: Mock, mock_client: Mock
):
    res_data = {
        "task_id": str(uuid.uuid4()),
        "status": random_string(),
        "result": random_string(),
        "exception": None,
    }
    mock_client._compute_web_client.v2.get_task.return_value = res_data
    mock_client.fx_serializer.deserialize.side_effect = Exception
    with pytest.raises(ToolError, match="Unable to deserialize result"):
        await globus_compute_get_task_status(task_ids=[res_data["task_id"]], ctx=mock_ctx)
