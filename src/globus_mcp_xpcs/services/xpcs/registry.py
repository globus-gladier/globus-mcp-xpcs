from mcp.server.fastmcp import FastMCP

from globus_mcp_xpcs.services.xpcs.tools import ALL_XPCS_TOOLS


def register_xpcs_tools(mcp: FastMCP) -> None:
    for tool in ALL_XPCS_TOOLS:
        mcp.add_tool(tool)
