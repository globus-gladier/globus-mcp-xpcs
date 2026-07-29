import argparse

from mcp.server.fastmcp import FastMCP

# Used for testing, should be removed
# from globus_mcp.auth import get_globus_app
from globus_mcp_xpcs.context import lifespan
from globus_mcp_xpcs.services.compute.registry import register_compute
from globus_mcp_xpcs.services.transfer.registry import register_transfer
from globus_mcp_xpcs.services.xpcs.registry import register_xpcs_tools

mcp = FastMCP("Globus MCP Server", lifespan=lifespan)


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
    # if parse_arguments().test:

    #     class LifespanContext:
    #         def __init__(self, app):
    #             self.app = app
    #             self.compute_client = None  # Placeholder for the compute client
    #             self.transfer_client = None  # Placeholder for the transfer client

    #     class RequestContext:
    #         def __init__(self, lifespan_context):
    #             self.lifespan_context = lifespan_context

    #     class Context:
    #         def __init__(self, request_context):
    #             self.request_context = request_context

    #     ctx = Context(
    #         request_context=RequestContext(lifespan_context=LifespanContext(app=get_globus_app()))
    #     )
    #     data = xpcs_ls_source(
    #         "/8IDI/2025-2/tempus202507-merge/data/converted/Cb0058_D100_a0011_f2000000/",
    #         ctx=ctx,
    #     )
    #     print(data)
    #     return

    args = parse_arguments()
    for service in args.services:
        service_registry[service](mcp)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
