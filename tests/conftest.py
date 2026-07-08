from unittest.mock import Mock

import pytest
from mcp.server.fastmcp import Context

from globus_mcp.context import GlobusContext


@pytest.fixture
def mock_app():
    app = Mock()
    app.config.environment = "sandbox"
    app.get_client_retry_checks.return_value = []
    return app


@pytest.fixture
def mock_ctx(mock_app: Mock):
    ctx = Mock(spec=Context)
    ctx.request_context.lifespan_context = GlobusContext(app=mock_app)
    return ctx


@pytest.fixture
def mock_config(monkeypatch):
    COMPUTE_ENDPOINTS = [
        {
            "uuid": "0535f8c4-a20e-47ed-a11d-c592da7574cf",
            "display_name": "Globus Compute Endpoint",
            "description": "Test Globus Compute Endpoint",
            "allowed_basepaths": [
                {
                    "path": "/compute_directory",
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

    COLLECTIONS = [
        {
            "type": "collection",
            "uuid": "9b91e88f-0731-439a-bed9-509768f37e24",
            "display_name": "Test Collection Foo",
            "description": "Globus Collection ",
            "collection_basepath": "/",
            "allowed_basepaths": [
                {
                    "path": "/foo-read-write-directory",
                    "permissions": "r",
                }
            ],
        },
        {
            "type": "collection",
            "uuid": "dc37d0e5-c9c7-49fb-b881-b8e15be215a5",
            "display_name": "Test Collection Bar",
            "description": "Globus Collection",
            "collection_basepath": "/eagle/APSDataProcessing/aps8idi/",
            "allowed_basepaths": [
                {
                    "path": "/bar-read-write-directory",
                    "permissions": "rw",
                },
                {
                    "path": "/bar-read-only-directory/",
                    "permissions": "r",
                },
            ],
        },
    ]
    monkeypatch.setattr("globus_mcp.config.COMPUTE_ENDPOINTS", COMPUTE_ENDPOINTS)
    monkeypatch.setattr("globus_mcp.config.COLLECTIONS", COLLECTIONS)
    return {"COMPUTE_ENDPOINTS": COMPUTE_ENDPOINTS, "COLLECTIONS": COLLECTIONS}
