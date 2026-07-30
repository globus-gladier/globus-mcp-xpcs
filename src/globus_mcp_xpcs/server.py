import argparse

from mcp.server.fastmcp import FastMCP

from globus_mcp_xpcs import config
from globus_mcp_xpcs.services.compute.registry import register_compute
from globus_mcp_xpcs.services.transfer.registry import register_transfer
from globus_mcp_xpcs.services.xpcs.registry import register_xpcs_tools

mcp = FastMCP("Globus MCP Server", stateless_http=True, host="127.0.0.1", port=8000)


service_registry = {
    "compute": register_compute,
    "transfer": register_transfer,
    "xpcs": register_xpcs_tools,
}
services = ["transfer", "compute", "xpcs"]


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
        "--test",
        action="store_true",
        help="Test new functionality",
    )
    return parser.parse_args()


def main() -> None:
    config.load_user_config()

    args = parse_arguments()
    for service in args.services:
        service_registry[service](mcp)

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
