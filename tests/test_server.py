from pathlib import Path
from unittest.mock import ANY, Mock, patch

import pytest

from globus_mcp_xpcs.server import main, services
from tests.utils import random_string


@patch("globus_mcp_xpcs.server.FastMCP")
def test_run_server_default(mock_fastmcp: Mock):
    mcp_instance = mock_fastmcp.return_value
    with patch("globus_mcp_xpcs.server._configure_console_logging") as mock_configure_logging:
        with patch("globus_mcp_xpcs.server.config.load_user_config") as mock_load_config:
            with patch(
                "globus_mcp_xpcs.server.config.set_mcp_transfer_acls_enabled"
            ) as mock_set_acls:
                with patch.dict(
                    "globus_mcp_xpcs.server.service_registry", {s: Mock() for s in services}
                ) as service_registry:
                    with patch("sys.argv", ["globus-mcp"]):
                        main()
                        mock_configure_logging.assert_called_once_with()
                        mock_load_config.assert_called_once_with(
                            Path("~/.globus-mcp-xpcs.json").expanduser()
                        )
                        mock_set_acls.assert_called_once_with(True)
                        mock_fastmcp.assert_called_once_with(
                            "Globus MCP Server",
                            stateless_http=True,
                            lifespan=ANY,
                            host="127.0.0.1",
                            port=8000,
                        )
                        for service in services:
                            service_registry[service].assert_called_once_with(mcp_instance)
                        mcp_instance.run.assert_called_once_with(transport="streamable-http")


@patch("globus_mcp_xpcs.server.FastMCP")
@pytest.mark.parametrize("registered", [services[: i + 1] for i in range(len(services))])
def test_run_server_with_select_services(mock_fastmcp: Mock, registered: list[str]):
    mcp_instance = mock_fastmcp.return_value
    with patch("globus_mcp_xpcs.server._configure_console_logging") as mock_configure_logging:
        with patch("globus_mcp_xpcs.server.config.load_user_config") as mock_load_config:
            with patch(
                "globus_mcp_xpcs.server.config.set_mcp_transfer_acls_enabled"
            ) as mock_set_acls:
                with patch.dict(
                    "globus_mcp_xpcs.server.service_registry", {s: Mock() for s in services}
                ) as service_registry:
                    args = ["globus-mcp", "--services"] + registered
                    with patch("sys.argv", args):
                        main()

                        mock_configure_logging.assert_called_once_with()
                        mock_load_config.assert_called_once_with(
                            Path("~/.globus-mcp-xpcs.json").expanduser()
                        )
                        mock_set_acls.assert_called_once_with(True)
                        for service in registered:
                            service_registry[service].assert_called_once_with(mcp_instance)

                        unregistered = set(services) - set(registered)
                        for service in unregistered:
                            service_registry[service].assert_not_called()

                        mcp_instance.run.assert_called_once_with(transport="streamable-http")


@patch("globus_mcp_xpcs.server.FastMCP")
def test_run_server_with_invalid_service(mock_fastmcp: Mock):
    with patch("globus_mcp_xpcs.server._configure_console_logging") as mock_configure_logging:
        with patch("globus_mcp_xpcs.server.config.load_user_config") as mock_load_config:
            args = ["globus-mcp", "--services", random_string()]
            with patch("sys.argv", args):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 2  # argparse error exit code
                mock_configure_logging.assert_not_called()
                mock_load_config.assert_not_called()
                mock_fastmcp.assert_not_called()


@patch("globus_mcp_xpcs.server.FastMCP")
def test_run_server_with_host_and_port(mock_fastmcp: Mock):
    mcp_instance = mock_fastmcp.return_value
    with patch("globus_mcp_xpcs.server._configure_console_logging") as mock_configure_logging:
        with patch("globus_mcp_xpcs.server.config.load_user_config") as mock_load_config:
            with patch(
                "globus_mcp_xpcs.server.config.set_mcp_transfer_acls_enabled"
            ) as mock_set_acls:
                with patch.dict(
                    "globus_mcp_xpcs.server.service_registry", {s: Mock() for s in services}
                ) as service_registry:
                    args = ["globus-mcp", "--host", "0.0.0.0", "--port", "9000"]
                    with patch("sys.argv", args):
                        main()

                        mock_configure_logging.assert_called_once_with()
                        mock_load_config.assert_called_once_with(
                            Path("~/.globus-mcp-xpcs.json").expanduser()
                        )
                        mock_set_acls.assert_called_once_with(True)
                        mock_fastmcp.assert_called_once_with(
                            "Globus MCP Server",
                            stateless_http=True,
                            lifespan=ANY,
                            host="0.0.0.0",
                            port=9000,
                        )
                        for service in services:
                            service_registry[service].assert_called_once_with(mcp_instance)

                        mcp_instance.run.assert_called_once_with(transport="streamable-http")


@patch("globus_mcp_xpcs.server.FastMCP")
def test_run_server_with_stdio_transport(mock_fastmcp: Mock):
    mcp_instance = mock_fastmcp.return_value
    with patch("globus_mcp_xpcs.server._configure_console_logging") as mock_configure_logging:
        with patch("globus_mcp_xpcs.server.config.load_user_config") as mock_load_config:
            with patch(
                "globus_mcp_xpcs.server.config.set_mcp_transfer_acls_enabled"
            ) as mock_set_acls:
                with patch.dict(
                    "globus_mcp_xpcs.server.service_registry", {s: Mock() for s in services}
                ) as service_registry:
                    args = ["globus-mcp", "--transport", "stdio"]
                    with patch("sys.argv", args):
                        main()

                        mock_configure_logging.assert_called_once_with()
                        mock_load_config.assert_called_once_with(
                            Path("~/.globus-mcp-xpcs.json").expanduser()
                        )
                        mock_set_acls.assert_called_once_with(True)
                        for service in services:
                            service_registry[service].assert_called_once_with(mcp_instance)

                        mcp_instance.run.assert_called_once_with(transport="stdio")


@patch("globus_mcp_xpcs.server.FastMCP")
def test_run_server_with_custom_config_path(mock_fastmcp: Mock):
    mcp_instance = mock_fastmcp.return_value
    with patch("globus_mcp_xpcs.server._configure_console_logging") as mock_configure_logging:
        with patch("globus_mcp_xpcs.server.config.load_user_config") as mock_load_config:
            with patch(
                "globus_mcp_xpcs.server.config.set_mcp_transfer_acls_enabled"
            ) as mock_set_acls:
                with patch.dict(
                    "globus_mcp_xpcs.server.service_registry", {s: Mock() for s in services}
                ) as service_registry:
                    args = ["globus-mcp", "--config", "/tmp/custom-config.json"]
                    with patch("sys.argv", args):
                        main()

                        mock_configure_logging.assert_called_once_with()
                        mock_load_config.assert_called_once_with(Path("/tmp/custom-config.json"))
                        mock_set_acls.assert_called_once_with(True)
                        for service in services:
                            service_registry[service].assert_called_once_with(mcp_instance)
                        mcp_instance.run.assert_called_once_with(transport="streamable-http")


@patch("globus_mcp_xpcs.server.FastMCP")
def test_run_server_with_disable_mcp_acls(mock_fastmcp: Mock):
    mcp_instance = mock_fastmcp.return_value
    with patch("globus_mcp_xpcs.server._configure_console_logging") as mock_configure_logging:
        with patch("globus_mcp_xpcs.server.config.load_user_config") as mock_load_config:
            with patch(
                "globus_mcp_xpcs.server.config.set_mcp_transfer_acls_enabled"
            ) as mock_set_acls:
                with patch.dict(
                    "globus_mcp_xpcs.server.service_registry", {s: Mock() for s in services}
                ) as service_registry:
                    args = ["globus-mcp", "--disable-mcp-transfer-acls"]
                    with patch("sys.argv", args):
                        main()

                        mock_configure_logging.assert_called_once_with()
                        mock_load_config.assert_called_once_with(
                            Path("~/.globus-mcp-xpcs.json").expanduser()
                        )
                        mock_set_acls.assert_called_once_with(False)
                        for service in services:
                            service_registry[service].assert_called_once_with(mcp_instance)
                        mcp_instance.run.assert_called_once_with(transport="streamable-http")
