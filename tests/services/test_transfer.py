import random
import uuid
from http import HTTPStatus
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from globus_sdk import GlobusAPIError, IterableTransferResponse, TransferClient, TransferData
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from globus_mcp_xpcs.context import GlobusContext
from globus_mcp_xpcs.server import service_registry
from globus_mcp_xpcs.services.transfer.client import get_transfer_client
from globus_mcp_xpcs.services.transfer.registry import register_transfer
from globus_mcp_xpcs.services.transfer.tools import (
    ALL_TRANSFER_TOOLS,
    _format_search_response,
    _handle_gare,
    _list_directory_entries_cached,
    globus_transfer_get_task_events,
    globus_transfer_get_task_progress,
    globus_transfer_list_directory,
    globus_transfer_submit_task,
)
from tests.utils import random_string


@pytest.fixture
def mock_client():
    with patch("globus_mcp_xpcs.services.transfer.tools.get_transfer_client") as mock_get_client:
        mc = Mock(spec=TransferClient)
        mock_get_client.return_value = mc
        yield mc


@pytest.fixture
def mock_handle_gare():
    with patch("globus_mcp_xpcs.services.transfer.tools._handle_gare") as _mock_handle_gare:
        yield _mock_handle_gare


@pytest.fixture
def mock_format_search_res():
    with patch(
        "globus_mcp_xpcs.services.transfer.tools._format_search_response"
    ) as _format_search_res:
        yield _format_search_res


def test_transfer_in_service_registry():
    assert "transfer" in service_registry
    assert service_registry["transfer"] is register_transfer


def test_register_transfer():
    mcp = Mock(spec=FastMCP)
    register_transfer(mcp)
    registered = [c[0][0] for c in mcp.add_tool.call_args_list]
    for tool in ALL_TRANSFER_TOOLS:
        assert tool in registered


def test_get_transfer_client(mock_ctx: Mock):
    globus_ctx: GlobusContext = mock_ctx.request_context.lifespan_context
    globus_ctx.app.app_name = random_string()
    assert globus_ctx.transfer_client is None, "Ensure setup"

    client = get_transfer_client(mock_ctx)
    assert globus_ctx.transfer_client is client
    assert isinstance(client, TransferClient)
    assert client.app_name == globus_ctx.app.app_name

    client_2 = get_transfer_client(mock_ctx)
    assert client_2 is client, "Client should be cached"


def test_handle_gare_happy_path(mock_client: Mock):
    res_data = random_string()
    mock_client.some_method = Mock()
    mock_client.some_method.return_value = res_data
    mock_client.some_method.__self__ = mock_client

    args = [random_string() for _ in range(random.randint(1, 10))]
    kwargs = {random_string(): random_string() for _ in range(random.randint(1, 10))}
    res = _handle_gare(mock_client.some_method, *args, **kwargs)

    assert res == res_data
    mock_client.some_method.assert_called_once_with(*args, **kwargs)


def test_handle_gare_consent_required(mock_client: Mock):
    error = GlobusAPIError(r=MagicMock())
    error.http_status = HTTPStatus.FORBIDDEN
    error.code = "ConsentRequired"
    required_scopes = [random_string() for _ in range(random.randint(1, 10))]
    error.info.consent_required.required_scopes = required_scopes

    res_data = random_string()
    mock_client.some_method = Mock()
    mock_client.some_method.side_effect = [error, res_data]
    mock_client.some_method.__self__ = mock_client

    args = [random_string() for _ in range(random.randint(1, 10))]
    kwargs = {random_string(): random_string() for _ in range(random.randint(1, 10))}
    res = _handle_gare(mock_client.some_method, *args, **kwargs)

    assert res == res_data
    assert mock_client.some_method.call_count == 2
    mock_client.some_method.assert_called_with(*args, **kwargs)
    added_scopes = [s[0][0] for s in mock_client.add_app_scope.call_args_list]
    for scope in required_scopes:
        assert scope in added_scopes


def test_handle_gare_unexpected_error(mock_client: Mock):
    error = GlobusAPIError(r=MagicMock())
    error.http_status = HTTPStatus.INTERNAL_SERVER_ERROR

    mock_client.some_method = Mock()
    mock_client.some_method.side_effect = error
    mock_client.some_method.__self__ = mock_client

    with pytest.raises(GlobusAPIError):
        _handle_gare(mock_client.some_method)


def test_format_search_response():
    res_data: dict[str, Any] = {
        "limit": random.randint(1, 1000),
        "offset": random.randint(0, 1000),
        "has_next_page": False,
        "DATA": [],
    }
    for _ in range(random.randint(1, 10)):
        res_data["DATA"].append(
            {
                "id": str(uuid.uuid4()),
                "display_name": random_string(),
                "owner_id": str(uuid.uuid4()),
                "owner_string": random_string(),
                "entity_type": random_string(),
                "description": random_string(),
            }
        )

    mock_res = Mock(spec=IterableTransferResponse)
    mock_res.__getitem__ = Mock(side_effect=lambda k: res_data[k])
    mock_res.get = Mock(side_effect=lambda k, d=None: res_data.get(k, d))
    mock_res.__iter__ = Mock(return_value=iter(res_data["DATA"]))

    res = _format_search_response(mock_res)

    assert res.limit == res_data["limit"]
    assert res.offset == res_data["offset"]
    assert res.has_next_page == res_data["has_next_page"]
    for idx, ep in enumerate(res.data):
        ep_data = res_data["DATA"][idx]
        assert ep.endpoint_id == ep_data["id"]
        assert ep.display_name == ep_data["display_name"]
        assert ep.owner_id == ep_data["owner_id"]
        assert ep.owner_string == ep_data["owner_string"]
        assert ep.type == ep_data["entity_type"]
        assert ep.description == ep_data["description"]


@pytest.mark.asyncio
async def test_globus_transfer_submit_task(
    mock_ctx: Mock, mock_client: Mock, mock_handle_gare: Mock, mock_config: dict[str, Any]
):
    label = random_string()
    task_id = str(uuid.uuid4())

    transfer_data = TransferData(
        source_endpoint=mock_config["COLLECTIONS"][0]["uuid"],
        destination_endpoint=mock_config["COLLECTIONS"][1]["uuid"],
        label=label,
    )
    transfer_data.add_item(
        source_path="/foo-read-write-directory",
        destination_path="/bar-read-write-directory",
        recursive=True,
    )
    transfer_data.add_item(
        source_path="/foo-read-write-directory/nested",
        destination_path="/bar-read-write-directory/nested",
        recursive=False,
    )

    mock_handle_gare.return_value = Mock(data={"task_id": task_id})
    mock_client.get_task.side_effect = [
        Mock(data={"task_id": task_id, "status": "ACTIVE", "files_transferred": 0}),
        Mock(data={"task_id": task_id, "status": "SUCCEEDED", "files_transferred": 2}),
    ]
    mock_client.task_event_list.return_value = {
        "limit": 10,
        "offset": 0,
        "DATA": [
            {
                "code": random_string(),
                "is_error": False,
                "description": random_string(),
                "details": random_string(),
                "time": random_string(),
            }
        ],
    }

    with patch("globus_mcp_xpcs.services.transfer.tools.asyncio.sleep", new_callable=AsyncMock):
        res = await globus_transfer_submit_task(
            source_collection_id=mock_config["COLLECTIONS"][0]["uuid"],
            destination_collection_id=mock_config["COLLECTIONS"][1]["uuid"],
            DATA=[
                {
                    "source_path": "/foo-read-write-directory",
                    "destination_path": "/bar-read-write-directory",
                    "recursive": True,
                },
                {
                    "source_path": "/foo-read-write-directory/nested",
                    "destination_path": "/bar-read-write-directory/nested",
                    "recursive": False,
                },
            ],
            label=label,
            timeout=1,
            polling_interval=1,
            limit=10,
            offset=0,
            ctx=mock_ctx,
        )

    mock_handle_gare.assert_called_once_with(mock_client.submit_transfer, transfer_data)
    assert mock_client.get_task.call_count == 2
    mock_client.task_event_list.assert_called_once_with(task_id, limit=10, offset=0)
    assert res.task_id == task_id
    assert res.completed is True
    assert res.task["status"] == "SUCCEEDED"
    assert len(res.events) == 1


@pytest.mark.asyncio
async def test_globus_transfer_submit_task_api_error(
    mock_ctx: Mock, mock_handle_gare: Mock, mock_config: dict[str, Any]
):
    mock_handle_gare.side_effect = GlobusAPIError(r=MagicMock())
    with pytest.raises(ToolError, match="Failed to submit transfer"):
        await globus_transfer_submit_task(
            source_collection_id=mock_config["COLLECTIONS"][0]["uuid"],
            destination_collection_id=mock_config["COLLECTIONS"][1]["uuid"],
            DATA=[
                {
                    "source_path": "/foo-read-write-directory",
                    "destination_path": "/bar-read-write-directory",
                    "recursive": False,
                }
            ],
            label=random_string(),
            ctx=mock_ctx,
        )


@pytest.mark.asyncio
async def test_globus_transfer_submit_task_rejects_disallowed_paths(
    mock_ctx: Mock, mock_config: dict[str, Any]
):
    with pytest.raises(ToolError, match="is not allowed"):
        await globus_transfer_submit_task(
            source_collection_id=mock_config["COLLECTIONS"][0]["uuid"],
            destination_collection_id=mock_config["COLLECTIONS"][1]["uuid"],
            DATA=[
                {
                    "source_path": "/not/allowed/source.h5",
                    "destination_path": "/bar-read-write-directory",
                    "recursive": False,
                }
            ],
            label=random_string(),
            ctx=mock_ctx,
        )


def test_globus_transfer_get_task_events(mock_ctx: Mock, mock_client: Mock):
    task_id = str(uuid.uuid4())

    res_data: dict[str, Any] = {
        "limit": random.randint(1, 1000),
        "offset": random.randint(0, 1000),
        "DATA": [],
    }
    for _ in range(random.randint(1, 10)):
        res_data["DATA"].append(
            {
                "code": random_string(),
                "is_error": False,
                "description": random_string(),
                "details": random_string(),
                "time": random_string(),
            }
        )
    mock_client.task_event_list.return_value = res_data

    res = globus_transfer_get_task_events(
        task_id=task_id, limit=res_data["limit"], offset=res_data["offset"], ctx=mock_ctx
    )

    mock_client.task_event_list.assert_called_once_with(
        task_id=task_id, limit=res_data["limit"], offset=res_data["offset"]
    )
    assert res.limit == res_data["limit"]
    assert res.offset == res_data["offset"]
    for idx, event in enumerate(res.data):
        event_data = res_data["DATA"][idx]
        assert event.code == event_data["code"]
        assert event.is_error is event_data["is_error"]
        assert event.description == event_data["description"]
        assert event.details == event_data["details"]
        assert event.time == event_data["time"]


def test_globus_transfer_get_task_events_api_error(mock_ctx: Mock, mock_client: Mock):
    mock_client.task_event_list.side_effect = GlobusAPIError(r=MagicMock())
    with pytest.raises(ToolError, match="Failed to get task events"):
        globus_transfer_get_task_events(task_id=str(uuid.uuid4()), limit=10, offset=0, ctx=mock_ctx)


@pytest.mark.asyncio
async def test_globus_transfer_get_task_progress(mock_ctx: Mock, mock_client: Mock):
    task_id = str(uuid.uuid4())

    events_res: dict[str, Any] = {
        "limit": 10,
        "offset": 0,
        "DATA": [
            {
                "code": random_string(),
                "is_error": False,
                "description": random_string(),
                "details": random_string(),
                "time": random_string(),
            }
        ],
    }
    mock_client.get_task.return_value = Mock(
        data={"task_id": task_id, "status": "SUCCEEDED", "files_transferred": 1}
    )
    mock_client.task_event_list.return_value = events_res

    res = await globus_transfer_get_task_progress(
        task_id=task_id,
        timeout=1,
        polling_interval=1,
        limit=10,
        offset=0,
        ctx=mock_ctx,
    )

    mock_client.get_task.assert_called_once_with(task_id)
    mock_client.task_event_list.assert_called_once_with(task_id, limit=10, offset=0)
    assert res.task_id == task_id
    assert res.completed is True
    assert res.task["status"] == "SUCCEEDED"
    assert res.events[0].code == events_res["DATA"][0]["code"]


def test_globus_transfer_list_directory(
    mock_ctx: Mock, mock_client: Mock, mock_config: dict[str, Any]
):
    collection_id = mock_config["COLLECTIONS"][0]["uuid"]
    path = "/foo-read-write-directory"

    res_data: dict[str, Any] = {
        "limit": random.randint(1, 1000),
        "offset": random.randint(0, 1000),
        "DATA": [],
    }
    for _ in range(random.randint(1, 10)):
        res_data["DATA"].append(
            {
                "name": random_string(),
                "type": random_string(),
                "link_target": random_string(),
                "user": random_string(),
                "group": random_string(),
                "permissions": random_string(),
                "size": random.randint(1, 1000),
                "last_modified": random_string(),
            }
        )
    mock_client.operation_ls.return_value = res_data

    res = globus_transfer_list_directory(
        collection_id=collection_id,
        path=path,
        filename_regex=None,
        limit=res_data["limit"],
        offset=res_data["offset"],
        ctx=mock_ctx,
    )

    mock_client.operation_ls.assert_called_once_with(
        collection_id,
        path=path,
        limit=100_000,
        offset=0,
    )
    assert res.basepath == path
    assert res.filenames == [
        file_data["name"]
        for file_data in res_data["DATA"][
            res_data["offset"] : res_data["offset"] + res_data["limit"]
        ]
    ]


def test_globus_transfer_list_directory_filters_and_caches(
    mock_ctx: Mock, mock_client: Mock, mock_config: dict[str, Any]
):
    collection_id = mock_config["COLLECTIONS"][0]["uuid"]
    path = "/foo-read-write-directory"
    _list_directory_entries_cached.cache_clear()
    mock_client.operation_ls.return_value = {
        "DATA": [
            {"name": "skip.dat"},
            {"name": "match_1.txt"},
            {"name": "match_2.txt"},
        ]
    }

    first = globus_transfer_list_directory(
        collection_id=collection_id,
        path=path,
        filename_regex=r"^match_.*\.txt$",
        limit=1,
        offset=0,
        ctx=mock_ctx,
    )
    second = globus_transfer_list_directory(
        collection_id=collection_id,
        path=path,
        filename_regex=r"^skip",
        limit=1,
        offset=0,
        ctx=mock_ctx,
    )
    third = globus_transfer_list_directory(
        collection_id=collection_id,
        path=path,
        filename_regex=r"^match_.*\.txt$",
        limit=1,
        offset=1,
        ctx=mock_ctx,
    )

    mock_client.operation_ls.assert_called_once_with(
        collection_id,
        path=path,
        limit=100_000,
        offset=0,
    )
    assert first.filenames == ["match_1.txt"]
    assert second.filenames == ["skip.dat"]
    assert third.filenames == ["match_2.txt"]
    assert first.basepath == path
    assert second.basepath == path
    assert third.basepath == path


def test_globus_transfer_list_directory_cached_false_bypasses_cache(
    mock_ctx: Mock, mock_client: Mock, mock_config: dict[str, Any]
):
    collection_id = mock_config["COLLECTIONS"][0]["uuid"]
    path = "/foo-read-write-directory"
    _list_directory_entries_cached.cache_clear()
    mock_client.operation_ls.side_effect = [
        {"DATA": [{"name": "cached.txt"}]},
        {"DATA": [{"name": "fresh.txt"}]},
    ]

    first = globus_transfer_list_directory(
        collection_id=collection_id,
        path=path,
        cached=True,
        filename_regex=None,
        limit=100,
        offset=0,
        ctx=mock_ctx,
    )
    second = globus_transfer_list_directory(
        collection_id=collection_id,
        path=path,
        cached=False,
        filename_regex=None,
        limit=100,
        offset=0,
        ctx=mock_ctx,
    )

    assert mock_client.operation_ls.call_count == 2
    assert first.filenames == ["cached.txt"]
    assert second.filenames == ["fresh.txt"]


def test_globus_transfer_list_directory_api_error(
    mock_ctx: Mock, mock_client: Mock, mock_config: dict[str, Any]
):
    _list_directory_entries_cached.cache_clear()
    mock_client.operation_ls.side_effect = GlobusAPIError(r=MagicMock())
    with pytest.raises(ToolError, match="Failed to list directory contents"):
        globus_transfer_list_directory(
            collection_id=mock_config["COLLECTIONS"][0]["uuid"],
            path="/foo-read-write-directory",
            filename_regex=None,
            limit=100,
            offset=0,
            ctx=mock_ctx,
        )


def test_globus_transfer_list_directory_invalid_regex(
    mock_ctx: Mock, mock_client: Mock, mock_config: dict[str, Any]
):
    _list_directory_entries_cached.cache_clear()
    with pytest.raises(ToolError, match="Invalid filename regex"):
        globus_transfer_list_directory(
            collection_id=mock_config["COLLECTIONS"][0]["uuid"],
            path="/foo-read-write-directory",
            filename_regex="[",
            limit=100,
            offset=0,
            ctx=mock_ctx,
        )

    mock_client.operation_ls.assert_not_called()
