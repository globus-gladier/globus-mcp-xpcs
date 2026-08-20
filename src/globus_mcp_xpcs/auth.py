import os

import globus_sdk

DEFAULT_CLIENT_ID = "f2a9c08a-4a6c-4524-936f-a4ec4fabb9bd"


def _get_client_creds() -> tuple[str | None, str | None]:
    client_id = os.getenv("GLOBUS_CLIENT_ID")
    client_secret = os.getenv("GLOBUS_CLIENT_SECRET")
    return client_id, client_secret


def get_globus_app() -> globus_sdk.GlobusApp:
    app_name = "Globus MCP Server"
    client_id, client_secret = _get_client_creds()

    if client_id and client_secret:
        return globus_sdk.ClientApp(
            app_name=app_name,
            client_id=client_id,
            client_secret=client_secret,
            config=globus_sdk.GlobusAppConfig(
                auto_redrive_gares=True,
            ),
        )
    else:
        raise ValueError(
            "Both GLOBUS_CLIENT_ID and GLOBUS_CLIENT_SECRET must be set in the environment."
        )
