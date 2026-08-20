import logging
import pathlib
import re
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated, Any

import globus_sdk
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.session import ServerSession
from pydantic import Field

from globus_mcp_xpcs import config
from globus_mcp_xpcs.context import GlobusContext
from globus_mcp_xpcs.services.transfer.client import get_transfer_client
from globus_mcp_xpcs.services.transfer.schemas import (
    CollectionBasepath,
    CollectionInfo,
    TransferDirectoryListing,
    TransferEvent,
    TransferEventList,
    TransferTaskProgress,
)

_TRANSFER_LS_PAGE_SIZE = 100_000

log = logging.getLogger(__name__)


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


def _normalize_posix_path(path: str) -> str:
    normalized = str(pathlib.PurePosixPath(path))
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized.rstrip("/") or "/"


def _list_directory_entries(
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


@lru_cache(maxsize=256)
def _list_directory_entries_cached(
    client: globus_sdk.TransferClient,
    collection_id: str,
    normalized_path: str,
) -> list[dict[str, Any]]:
    return _list_directory_entries(client, collection_id, normalized_path)


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
    if not config.is_mcp_transfer_acls_enabled():
        return

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


def globus_transfer_submit_task(
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
        res = client.submit_transfer(data)

        return TransferTaskProgress(
            task_id=res.data["task_id"],
            completed=res.data.get("status", "").upper() in {"SUCCEEDED", "FAILED"},
            task=res.data,
            events=[],
        )
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to submit transfer: {e}") from e
    except Exception as e:
        log.exception("Unexpected error during transfer submission")
        raise ToolError(f"Unexpected error during transfer submission: {e}") from e


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


def globus_transfer_get_task_progress(
    task_id: Annotated[str, Field(description="ID of the task")],
    ctx: Context[ServerSession, GlobusContext],
) -> TransferTaskProgress:
    """Wait for a transfer task to make progress, then return its status and recent events.

    The tool returns once the task finishes or the timeout expires.
    """
    client = get_transfer_client(ctx)
    try:
        res = client.get_task(task_id)
        return TransferTaskProgress(
            task_id=res.data["task_id"],
            completed=res.data.get("status", "").upper() in {"SUCCEEDED", "FAILED"},
            task=res.data,
            events=[],
        )
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to get task progress: {e}") from e
    except Exception as e:
        log.exception("Unexpected error during transfer task progress retrieval")
        raise ToolError(f"Unexpected error during transfer task progress retrieval: {e}") from e


def globus_transfer_task_list(
    ctx: Context[ServerSession, GlobusContext],
    limit: Annotated[
        int,
        Field(description="Maximum number of results to return."),
    ] = 10,
) -> TransferTaskProgress:
    """
    limit (int | MissingType) - limit the number of results
    offset (int | MissingType) -  offset used in paging
    """
    client = get_transfer_client(ctx)
    try:
        res = client.task_list(limit=limit)
        return TransferTaskProgress(
            task_id=res.data["task_id"],
            completed=res.data.get("status", "").upper() in {"SUCCEEDED", "FAILED"},
            task=res.data,
            events=[],
        )
    except globus_sdk.GlobusAPIError as e:
        raise ToolError(f"Failed to get task progress: {e}") from e
    except Exception as e:
        log.exception("Unexpected error during transfer task progress retrieval")
        raise ToolError(f"Unexpected error during transfer task progress retrieval: {e}") from e


def globus_transfer_list_directory(
    collection_id: Annotated[str, Field(description="ID of the collection")],
    path: Annotated[str, Field(description="Path to a directory")],
    ctx: Context[ServerSession, GlobusContext],
    cached: Annotated[
        bool,
        Field(
            default=True,
            description=(
                "Caching is better on source directories that are not frequently updated. "
                "Caching should always be used on read-only directories."
                "Set to false if monitoring for new files in a frequently updated directory."
            ),
        ),
    ] = True,
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

    If cached is true, the tool may reuse a cached directory listing for the same collection and
    path. If filename_regex is provided, filtering is applied before limit and offset pagination.
    """
    client = get_transfer_client(ctx)
    normalized_path = _normalize_posix_path(path)

    _assert_collection_path_allowed(collection_id, normalized_path, "r")

    try:
        pattern = re.compile(filename_regex) if filename_regex is not None else None
    except re.error as e:
        raise ToolError(f"Invalid filename regex '{filename_regex}': {e}") from e

    if cached:
        entries = _list_directory_entries_cached(client, collection_id, normalized_path)
    else:
        entries = _list_directory_entries(client, collection_id, normalized_path)
    filenames = [str(entry["name"]) for entry in entries]
    if pattern is not None:
        filenames = [name for name in filenames if pattern.search(name)]

    filenames = filenames[offset : offset + limit]

    return TransferDirectoryListing(filenames=filenames, basepath=normalized_path)


def list_collections() -> list[CollectionInfo]:
    """List the configured XPCS Globus Transfer collections and their allowed
    filesystem paths/permissions."""
    acls_enabled = config.is_mcp_transfer_acls_enabled()

    return [
        CollectionInfo(
            uuid=col["uuid"],
            display_name=col["display_name"],
            description=col["description"],
            collection_basepath=col["collection_basepath"],
            allowed_basepaths=(
                [CollectionBasepath(path="/", permissions="rw")]
                if not acls_enabled
                else [
                    CollectionBasepath(
                        path=bp["path"],
                        permissions=bp["permissions"],
                    )
                    for bp in col.get("allowed_basepaths", [])
                ]
            ),
        )
        for col in config.COLLECTIONS
    ]


ALL_TRANSFER_TOOLS: list[Callable[..., Any]] = [
    globus_transfer_submit_task,
    globus_transfer_get_task_events,
    globus_transfer_get_task_progress,
    globus_transfer_task_list,
    globus_transfer_list_directory,
    list_collections,
]
