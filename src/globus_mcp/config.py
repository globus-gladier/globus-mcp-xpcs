from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# GLOBUS_ENDPOINT_VOYAGER = "ed03fe07-632e-47a9-9df7-9b8b236ac0b4"
# GLOBUS_ENDPOINT_EAGLE_APS_DATA_PROCESSING = "98d26f35-e5d5-4edd-becf-a75520656c64"
# GLOBUS_COMPUTE_ENDPOINT = "f8f4692a-0ab7-40d0-b256-ba5b82b5e2ec"
DEFAULT_COMPUTE_ENDPOINT = "f8f4692a-0ab7-40d0-b256-ba5b82b5e2ec"
COMPUTE_ENDPOINTS: list[dict[str, Any]] = [
    {
        "uuid": "d88919ea-026a-493e-9124-fe3c46defa54",
        "display_name": "Globus Compute Endpoint",
        "description": "Globus Compute Endpoint for XPCS processing",
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
        "description": "Globus Collection for source data for XPCS processing",
        "collection_basepath": "/",
        "allowed_basepaths": [
            {
                "path": "/8IDI/2025-2/tempus202507-merge/data/converted",
                "permissions": "r",
            }
        ],
    },
    {
        "type": "collection",
        "uuid": "98d26f35-e5d5-4edd-becf-a75520656c64",
        "display_name": "Eagle APS Data Processing",
        "description": "Globus Collection for source data for XPCS processing",
        "collection_basepath": "/eagle/APSDataProcessing/aps8idi/",
        "allowed_basepaths": [
            {
                "path": "/xpcs_staging/agentic-testing/",
                "permissions": "rw",
            },
            {
                "path": "/xpcs_staging/",
                "permissions": "r",
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
