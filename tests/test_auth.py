import uuid

import pytest
from globus_sdk import ClientApp
from pytest import MonkeyPatch

from globus_mcp_xpcs.auth import get_globus_app
from tests.utils import random_string


def test_get_globus_app_custom_client_id_and_secret(monkeypatch: MonkeyPatch):
    client_id = str(uuid.uuid4())
    client_secret = random_string()
    monkeypatch.setenv("GLOBUS_CLIENT_ID", client_id)
    monkeypatch.setenv("GLOBUS_CLIENT_SECRET", client_secret)
    app = get_globus_app()
    assert isinstance(app, ClientApp)
    assert app.client_id == client_id


def test_get_globus_app_missing_client_id(monkeypatch: MonkeyPatch):
    client_secret = random_string()
    monkeypatch.setenv("GLOBUS_CLIENT_SECRET", client_secret)
    with pytest.raises(ValueError) as exc_info:
        get_globus_app()
    assert "Both GLOBUS_CLIENT_ID and GLOBUS_CLIENT_SECRET must be set in the environment." in str(
        exc_info.value
    )
