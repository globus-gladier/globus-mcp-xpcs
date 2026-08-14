import argparse
import logging
import logging.config
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from globus_mcp_xpcs import config
from globus_mcp_xpcs.context import lifespan
from globus_mcp_xpcs.services.compute.registry import register_compute
from globus_mcp_xpcs.services.transfer.registry import register_transfer
from globus_mcp_xpcs.services.xpcs.registry import register_xpcs_tools

log = logging.getLogger(__name__)
service_registry = {
    "compute": register_compute,
    "transfer": register_transfer,
    "xpcs": register_xpcs_tools,
}
services = ["transfer", "compute", "xpcs"]
transports = ["streamable-http", "stdio"]


def _configure_console_logging() -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "formatters": {
                "basic": {"format": "[%(levelname)s] %(name)s::%(funcName)s() %(message)s"}
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": "DEBUG",
                    "formatter": "basic",
                }
            },
            "loggers": {
                "globus_mcp_xpcs": {"level": "DEBUG", "handlers": ["console"]},
            },
        }
    )
    log.debug("Console logging configured.")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Globus MCP Server")
    parser.add_argument(
        "--services",
        nargs="+",
        choices=services,
        default=services,
        help="Globus services to install tools for. Defaults to all services.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind the HTTP server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind the HTTP server.",
    )
    parser.add_argument(
        "--transport",
        choices=transports,
        default="streamable-http",
        help="Transport for MCP server. Defaults to streamable-http.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to a JSON config file. Defaults to ~/.globus-mcp-xpcs.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    _configure_console_logging()

    config_path = args.config or config.USER_CONFIG_PATH
    log.info("Using config file: %s", config_path)
    config.load_user_config(args.config)

    mcp = FastMCP(
        "Globus MCP Server",
        stateless_http=True,
        lifespan=lifespan,
        host=args.host,
        port=args.port,
    )

    for service in args.services:
        service_registry[service](mcp)

    try:
        mcp.run(transport=args.transport)
    except KeyboardInterrupt:
        log.info("Shutting down Globus MCP XPCS Server...")


if __name__ == "__main__":
    main()
