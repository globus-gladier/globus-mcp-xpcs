import asyncio
import pathlib
import re
import time
from collections.abc import Callable
from functools import lru_cache
from http import HTTPStatus
from typing import Annotated, Any, Literal

import globus_sdk
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from pydantic import Field

from globus_mcp import config
from globus_mcp.context import GlobusContext
from globus_mcp.services.transfer.client import get_transfer_client
from globus_mcp.services.transfer.schemas import (
    TransferDirectoryListing,
    TransferEndpoint,
    TransferEndpointList,
    TransferEvent,
    TransferEventList,
    TransferTaskProgress,
)

_TRANSFER_LS_PAGE_SIZE = 100_000


def _handle_gare(
    client_method: Callable[..., globus_sdk.GlobusHTTPResponse],
    *args: Any,
    **kwargs: Any,
) -> globus_sdk.GlobusHTTPResponse:
    client: globus_sdk.TransferClient = client_method.__self__  # type: ignore[attr-defined]
    try:
        return client_method(*args, **kwargs)
    except globus_sdk.GlobusAPIError as e:
        if e.http_status == HTTPStatus.FORBIDDEN and e.code == "ConsentRequired":
            scopes = e.info.consent_required.required_scopes
            for scope in scopes:
                client.add_app_scope(scope)
            return client_method(*args, **kwargs)
        raise


def _format_search_response(
    res: globus_sdk.IterableTransferResponse,
) -> TransferEndpointList:
    endpoints = []
    for e in res["DATA"]:
        endpoint = TransferEndpoint(
            endpoint_id=e["id"],
            display_name=e["display_name"],
            owner_id=e["owner_id"],
            owner_string=e["owner_string"],
            type=e["entity_type"],
            description=e.get("description"),
        )
        endpoints.append(endpoint)
    return TransferEndpointList(
        limit=res["limit"],
        offset=res["offset"],
        has_next_page=res["has_next_page"],
        data=endpoints,
    )


def _format_task_events_response(res: globus_sdk.IterableTransferResponse) -> TransferEventList:
    events = []
    for ev in res["DATA"]:
        event = TransferEvent(
            code=ev["code"],
            is_error=ev["is_error"],
            description=ev["description"],
            details=ev["details"],
            time=ev["time"],
        )
        events.append(event)

    return TransferEventList(limit=res["limit"], offset=res["offset"], data=events)


async def _get_task_progress(
    client: globus_sdk.TransferClient,
    task_id: str,
    timeout: int,
    polling_interval: int,
    limit: int,
    offset: int,
) -> TransferTaskProgress:
    start_time = time.monotonic()
    completed = False

    try:
        task_res = await asyncio.to_thread(client.get_task, task_id)
        while True:
            status = str(task_res.data.get("status", "")).upper()
            if status in {"SUCCEEDED", "FAILED"}:
                completed = True
                break

            elapsed = time.monotonic() - start_time
            remaining = timeout - elapsed
            if remaining <= 0:
                break

            await asyncio.sleep(min(float(polling_interval), remaining))
            task_res = await asyncio.to_thread(client.get_task, task_id)

        events_res = await asyncio.to_thread(
            client.task_event_list,
            task_id,
            limit=limit,
            offset=offset,
        )
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to get task progress: {e}") from e

    task_data = dict(task_res.data)
    events = _format_task_events_response(events_res).data

    return TransferTaskProgress(
        task_id=task_data.get("task_id", task_id),
        completed=completed,
        task=task_data,
        events=events,
    )


def _normalize_posix_path(path: str) -> str:
    normalized = str(pathlib.PurePosixPath(path))
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized.rstrip("/") or "/"


@lru_cache(maxsize=256)
def _list_directory_entries_cached(
    client: globus_sdk.TransferClient,
    collection_id: str,
    normalized_path: str,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    offset = 0
    while True:
        try:
            res = client.operation_ls(
                collection_id,
                path=normalized_path,
                limit=_TRANSFER_LS_PAGE_SIZE,
                offset=offset,
            )
        except globus_sdk.GlobusAPIError as e:
            raise ToolError(f"Failed to list directory contents: {e}") from e

        page_entries = [dict(item) for item in res["DATA"]]
        entries.extend(page_entries)
        if len(page_entries) < _TRANSFER_LS_PAGE_SIZE:
            return entries

        offset += _TRANSFER_LS_PAGE_SIZE


def _resolve_allowed_basepath(collection: dict[str, Any], allowed_basepath: str) -> str:
    collection_basepath = str(collection.get("collection_basepath", "/"))
    if allowed_basepath.startswith("/"):
        resolved = allowed_basepath
    else:
        resolved = str(pathlib.PurePosixPath(collection_basepath) / allowed_basepath.lstrip("/"))
    return _normalize_posix_path(resolved)


def _collection_has_access(collection_id: str, path: str, permission: str) -> bool:
    collection = config.get_collection(collection_id)
    if collection is None:
        return False

    normalized_path = _normalize_posix_path(path)
    for basepath in collection.get("allowed_basepaths", []):
        permissions = str(basepath.get("permissions", ""))
        if permission not in permissions:
            continue

        normalized_basepath = _resolve_allowed_basepath(collection, str(basepath["path"]))
        if normalized_basepath == "/":
            return True

        if normalized_path == normalized_basepath:
            return True

        if normalized_path.startswith(f"{normalized_basepath}/"):
            return True

    return False


def _assert_collection_path_allowed(collection_id: str, path: str, permission: str) -> None:
    collection = config.get_collection(collection_id)
    if collection is None:
        raise ToolError(f"Unknown collection_id '{collection_id}'")

    if not _collection_has_access(collection_id, path, permission):
        allowed_paths = [
            _resolve_allowed_basepath(collection, str(basepath["path"]))
            for basepath in collection.get("allowed_basepaths", [])
            if permission in str(basepath.get("permissions", ""))
        ]
        raise ToolError(
            f"Path '{path}' is not allowed for collection '{collection_id}'. "
            f"Allowed basepaths for permission '{permission}': {allowed_paths}"
        )


def globus_transfer_list_endpoints_and_collections(
    filter_scope: Annotated[
        Literal[
            "my-endpoints",
            "administered-by-me",
            "shared-with-me",
            "shared-by-me",
            "recently-used",
            "in-use",
        ],
        Field(
            description=(
                "String indicating which scope/class of endpoints and collections to list."
                " Options:"
                " my-endpoints (owned by the user),"
                " administered-by-me (user has admin role, superset of my-endpoints),"
                " shared-with-me (shared with user),"
                " shared-by-me (guest collections where user is admin or access manager),"
                " recently-used (recently used by user),"
                " in-use (with active tasks owned by user),"
            ),
        ),
    ],
    limit: Annotated[
        int,
        Field(default=100, le=100, description="Maximum number of results to return."),
    ],
    offset: Annotated[int, Field(default=0, description="Zero based offset into the result set.")],
    ctx: Context[ServerSession, GlobusContext],
) -> TransferEndpointList:
    """List Globus Transfer endpoints and collections that the user has access to, filtered based
    on the provided scope.
    """
    client = get_transfer_client(ctx)

    try:
        res = client.endpoint_search(
            filter_scope=filter_scope,
            limit=limit,
            offset=offset,
        )
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to get search results: {e}") from e

    return _format_search_response(res)


def globus_transfer_search_endpoints_and_collections(
    filter_fulltext: Annotated[
        str,
        Field(min_length=1, description=("String to match endpoint fields against.")),
    ],
    limit: Annotated[
        int,
        Field(default=100, le=100, description="Maximum number of results to return."),
    ],
    offset: Annotated[int, Field(default=0, description="Zero based offset into the result set.")],
    ctx: Context[ServerSession, GlobusContext],
) -> TransferEndpointList:
    """Use a filter string to search all Globus Transfer endpoints and collections that
    are visible to the user.
    """
    client = get_transfer_client(ctx)

    try:
        res = client.endpoint_search(
            filter_scope="all",
            filter_fulltext=filter_fulltext,
            limit=limit,
            offset=offset,
        )
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to get search results: {e}") from e

    return _format_search_response(res)


async def globus_transfer_submit_task(
    source_collection_id: Annotated[str, Field(description="ID of the source collection")],
    destination_collection_id: Annotated[
        str, Field(description="ID of the destination collection")
    ],
    DATA: Annotated[
        list[dict[str, Any]],
        Field(
            description=(
                "Transfer items to submit. Each item must include source_path, "
                "destination_path, and recursive."
            ),
        ),
    ],
    label: Annotated[
        str,
        Field(default="Globus MCP Transfer", description="Label for the transfer task"),
    ],
    ctx: Context[ServerSession, GlobusContext],
    timeout: Annotated[
        int,
        Field(default=600, ge=1, description="Maximum number of seconds to wait for completion."),
    ] = 600,
    polling_interval: Annotated[
        int,
        Field(default=10, ge=1, description="Seconds between status checks while waiting."),
    ] = 10,
    limit: Annotated[
        int,
        Field(default=10, le=1_000, description="Maximum number of events to return."),
    ] = 10,
    offset: Annotated[
        int, Field(default=0, description="Zero based offset into the result set.")
    ] = 0,
) -> TransferTaskProgress:
    """Submit a transfer task between two Globus Transfer collections.

    This tool waits for completion (or timeout) and returns current task status and events.
    """
    client = get_transfer_client(ctx)

    data = globus_sdk.TransferData(
        source_endpoint=source_collection_id,
        destination_endpoint=destination_collection_id,
        label=label,
    )

    for item in DATA:
        source_path = str(item["source_path"])
        destination_path = str(item["destination_path"])
        recursive = bool(item["recursive"])

        _assert_collection_path_allowed(source_collection_id, source_path, "r")
        _assert_collection_path_allowed(destination_collection_id, destination_path, "w")

        data.add_item(
            source_path=source_path,
            destination_path=destination_path,
            recursive=recursive,
        )

    try:
        res = _handle_gare(client.submit_transfer, data)
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to submit transfer: {e}") from e

    return await _get_task_progress(
        client=client,
        task_id=res.data["task_id"],
        timeout=timeout,
        polling_interval=polling_interval,
        limit=limit,
        offset=offset,
    )


def globus_transfer_get_task_events(
    task_id: Annotated[str, Field(description="ID of the task")],
    limit: Annotated[
        int,
        Field(default=10, le=1_000, description="Maximum number of results to return."),
    ],
    offset: Annotated[int, Field(default=0, description="Zero based offset into the result set.")],
    ctx: Context[ServerSession, GlobusContext],
) -> TransferEventList:
    """Get a list of Globus Transfer task events to monitor the status and progress of a task.
    The events are ordered by time descending (newest first).
    """
    client = get_transfer_client(ctx)

    try:
        res = client.task_event_list(task_id=task_id, limit=limit, offset=offset)
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to get task events: {e}") from e

    return _format_task_events_response(res)


async def globus_transfer_get_task_progress(
    task_id: Annotated[str, Field(description="ID of the task")],
    timeout: Annotated[
        int,
        Field(default=10, ge=1, description="Maximum number of seconds to wait for progress."),
    ],
    polling_interval: Annotated[
        int,
        Field(default=10, ge=1, description="Seconds between progress checks."),
    ],
    limit: Annotated[
        int,
        Field(default=10, le=1_000, description="Maximum number of events to return."),
    ],
    offset: Annotated[int, Field(default=0, description="Zero based offset into the result set.")],
    ctx: Context[ServerSession, GlobusContext],
) -> TransferTaskProgress:
    """Wait for a transfer task to make progress, then return its status and recent events.

    The tool returns once the task finishes or the timeout expires.
    """
    client = get_transfer_client(ctx)
    return await _get_task_progress(
        client=client,
        task_id=task_id,
        timeout=timeout,
        polling_interval=polling_interval,
        limit=limit,
        offset=offset,
    )


def globus_transfer_list_directory(
    collection_id: Annotated[str, Field(description="ID of the collection")],
    path: Annotated[str, Field(description="Path to a directory")],
    ctx: Context[ServerSession, GlobusContext],
    filename_regex: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional regex filter applied to the full directory listing before limit/offset "
                "pagination is applied."
            ),
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(default=100, le=100_000, description="Maximum number of results to return."),
    ] = 100,
    offset: Annotated[
        int,
        Field(default=0, description="Zero based offset into the result set."),
    ] = 0,
) -> TransferDirectoryListing:
    """List contents of a directory on a Globus Transfer collection.

    If filename_regex is provided, filtering is applied before limit and offset pagination.
    """
    client = get_transfer_client(ctx)
    normalized_path = _normalize_posix_path(path)

    _assert_collection_path_allowed(collection_id, normalized_path, "r")

    try:
        pattern = re.compile(filename_regex) if filename_regex is not None else None
    except re.error as e:
        raise ToolError(f"Invalid filename regex '{filename_regex}': {e}") from e

    entries = _list_directory_entries_cached(client, collection_id, normalized_path)
    filenames = [str(entry["name"]) for entry in entries]
    if pattern is not None:
        filenames = [name for name in filenames if pattern.search(name)]

    filenames = filenames[offset : offset + limit]

    return TransferDirectoryListing(filenames=filenames, basepath=normalized_path)


ALL_TRANSFER_TOOLS: list[Callable[..., Any]] = [
    globus_transfer_search_endpoints_and_collections,
    globus_transfer_list_endpoints_and_collections,
    globus_transfer_submit_task,
    globus_transfer_get_task_events,
    globus_transfer_get_task_progress,
    globus_transfer_list_directory,
]
