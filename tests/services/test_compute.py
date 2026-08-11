import uuid
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from globus_compute_sdk import Client
from globus_compute_sdk.serialize import JSONData, PureSourceTextInspect
from globus_sdk import GlobusAPIError
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from globus_mcp_xpcs.context import GlobusContext
from globus_mcp_xpcs.server import service_registry
from globus_mcp_xpcs.services.compute.client import get_compute_client
from globus_mcp_xpcs.services.compute.registry import register_compute
from globus_mcp_xpcs.services.compute.tools import (
    ALL_COMPUTE_TOOLS,
    globus_compute_get_task_status,
)
from tests.utils import random_string


@pytest.fixture
def mock_client():
    with patch("globus_mcp_xpcs.services.compute.tools.get_compute_client") as mock_get_client:
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
        "globus_mcp_xpcs.services.compute.tools.asyncio.sleep",
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
