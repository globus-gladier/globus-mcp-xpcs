import json

from globus_mcp_xpcs import config


def test_load_user_config_creates_missing_file_and_loads_defaults(tmp_path):
    config_path = tmp_path / "globus-mcp-xpcs.json"

    original_default = config.DEFAULT_COMPUTE_ENDPOINT
    original_endpoints = config.COMPUTE_ENDPOINTS
    original_collections = config.COLLECTIONS

    try:
        config.load_user_config(config_path)

        assert config_path.exists()
        payload = json.loads(config_path.read_text())
        assert payload["DEFAULT_COMPUTE_ENDPOINT"] == original_default
        assert payload["COMPUTE_ENDPOINTS"] == original_endpoints
        assert payload["COLLECTIONS"] == original_collections
    finally:
        config.DEFAULT_COMPUTE_ENDPOINT = original_default
        config.COMPUTE_ENDPOINTS = original_endpoints
        config.COLLECTIONS = original_collections
