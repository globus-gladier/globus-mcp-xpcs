# Globus MCP Server

The Globus [MCP](https://modelcontextprotocol.io) Server enables LLM applications to interact
with [Globus](https://www.globus.org/) services.

## Supported Tools

### XPCS

- `run_xpcs_boost_corr` - Submit a compute function that executes the `boost_corr` executable
  using `raw` and `qmap` inputs
- `xpcs_ls_source` - List files in an allowed source directory on the configured source endpoint
- `xpcs_transfer_data` - Submit a transfer task for one or more source/destination pairs to eagle for processing

## Configuration

The following configuration is compatible with most LLM applications that support MCP such as
[Claude Desktop](https://modelcontextprotocol.io/docs/develop/connect-local-servers):

```json
{
  "mcpServers": {
    "globus-mcp": {
      "command": "uvx",
      "args": ["globus-mcp"]
    }
  }
}
```

### Limiting Tool Registration

By default, the Globus MCP server registers tools for every service. To register tools for only
specific services, use the `--services` command-line flag:

```json
{
  "mcpServers": {
    "globus-mcp": {
      "command": "uvx",
      "args": [
        "globus-mcp",
        "--services",
        "xpcs"
      ]
    }
  }
}
```

### Specifying Client Credentials

If you've [registered a client application](https://docs.globus.org/api/auth/developer-guide/#register-app)
in the [Globus web UI](https://app.globus.org/settings/developers/), you can specify the client
credentials via the `GLOBUS_CLIENT_ID` and `GLOBUS_CLIENT_SECRET` environment variables:

```json
{
  "mcpServers": {
    "globus-mcp": {
      "command": "uvx",
      "args": ["globus-mcp"],
      "env": {
        "GLOBUS_CLIENT_ID": "...",
        "GLOBUS_CLIENT_SECRET": "..."
      }
    }
  }
}
```