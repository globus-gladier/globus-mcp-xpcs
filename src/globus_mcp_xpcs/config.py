from __future__ import annotations

import copy
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

USER_CONFIG_PATH = Path("~/.globus-mcp-xpcs.json").expanduser()

DEFAULT_COMPUTE_ENDPOINT = "d88919ea-026a-493e-9124-fe3c46defa54"
COMPUTE_ENDPOINTS: list[dict[str, Any]] = [
    {
        "uuid": "d88919ea-026a-493e-9124-fe3c46defa54",
        "display_name": "Globus Compute Endpoint",
        "description": "Globus Compute Endpoint for XPCS processing on eagle",
        "filesystem": "eagle",
        "allowed_basepaths": [
            {
                "path": "/eagle/APSDataProcessing/aps8idi/xpcs_staging/agentic-testing/",
                "permissions": "rw",
            }
        ],
        "config": {
            "queue": "debug",
            "walltime": "1:00:00",
            "nodes_per_block": 1,
            "max_blocks": 5,
        },
    }
]

COLLECTIONS: list[dict[str, Any]] = [
    {
        "type": "collection",
        "uuid": "ed03fe07-632e-47a9-9df7-9b8b236ac0b4",
        "display_name": "Voyager",
        "filesystem": "voyager",
        "description": "The voyager Globus Collection containing source datasets for xpcs",
        "collection_basepath": "/",
        "allowed_basepaths": [
            {
                "path": "/8IDI/2025-2/tempus202507-merge/data/converted",
                "permissions": "r",
            },
            {
                "path": "/8IDI/2025-2/tempus202507-merge/data/",
                "permissions": "r",
            },
            {
                "path": "/8IDI/2026-2/tingxu202606/data",
                "permissions": "r",
            },
        ],
    },
    {
        "type": "collection",
        "uuid": "98d26f35-e5d5-4edd-becf-a75520656c64",
        "display_name": "Eagle APS Data Processing",
        "filesystem": "eagle",
        "description": (
            "Globus Collection for staging XPCS data on the eagle cluster "
            "for processing with Globus Compute"
        ),
        "collection_basepath": "/eagle/APSDataProcessing/aps8idi/",
        "allowed_basepaths": [
            {
                "path": "/xpcs_staging/agentic-testing/",
                "permissions": "rw",
            },
        ],
    },
]


def get_collection(collection_id: str) -> dict[str, Any] | None:
    for collection in COLLECTIONS:
        if collection["uuid"] == collection_id:
            return collection
    return None


def iter_collection_ids() -> Iterable[str]:
    return (collection["uuid"] for collection in COLLECTIONS)


def get_endpoint(endpoint_id: str) -> dict[str, Any] | None:
    for endpoint in COMPUTE_ENDPOINTS:
        if endpoint["uuid"] == endpoint_id:
            return endpoint
    return None


def _current_config_payload() -> dict[str, Any]:
    return {
        "DEFAULT_COMPUTE_ENDPOINT": DEFAULT_COMPUTE_ENDPOINT,
        "COMPUTE_ENDPOINTS": copy.deepcopy(COMPUTE_ENDPOINTS),
        "COLLECTIONS": copy.deepcopy(COLLECTIONS),
    }


def _apply_config_payload(payload: dict[str, Any]) -> None:
    global DEFAULT_COMPUTE_ENDPOINT
    global COMPUTE_ENDPOINTS
    global COLLECTIONS

    default_endpoint = payload.get("DEFAULT_COMPUTE_ENDPOINT", DEFAULT_COMPUTE_ENDPOINT)
    endpoints = payload.get("COMPUTE_ENDPOINTS", COMPUTE_ENDPOINTS)
    collections = payload.get("COLLECTIONS", COLLECTIONS)

    if not isinstance(default_endpoint, str):
        raise ValueError("DEFAULT_COMPUTE_ENDPOINT must be a string")
    if not isinstance(endpoints, list) or not all(isinstance(ep, dict) for ep in endpoints):
        raise ValueError("COMPUTE_ENDPOINTS must be a list of objects")
    if not isinstance(collections, list) or not all(isinstance(col, dict) for col in collections):
        raise ValueError("COLLECTIONS must be a list of objects")

    DEFAULT_COMPUTE_ENDPOINT = default_endpoint
    COMPUTE_ENDPOINTS = [dict(ep) for ep in endpoints]
    COLLECTIONS = [dict(col) for col in collections]


def load_user_config(config_path: Path | None = None) -> None:
    path = config_path or USER_CONFIG_PATH

    if not path.exists():
        path.write_text(json.dumps(_current_config_payload(), indent=2) + "\n")

    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError("Config file must be a JSON object")

    _apply_config_payload(payload)
