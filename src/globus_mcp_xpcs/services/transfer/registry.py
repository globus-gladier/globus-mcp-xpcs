from mcp.server.fastmcp import FastMCP

from globus_mcp_xpcs.services.transfer.tools import ALL_TRANSFER_TOOLS


def register_transfer(mcp: FastMCP) -> None:
    for tool in ALL_TRANSFER_TOOLS:
        mcp.add_tool(tool)
