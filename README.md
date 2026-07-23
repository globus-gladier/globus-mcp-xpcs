# Globus MCP Server

The Globus [MCP](https://modelcontextprotocol.io) Server enables LLM applications to interact
with [Globus](https://www.globus.org/) services.


## Recommended prompts

These are example prompts that can be used with this mcp server.

#### Prompt 1:

Run Multitau analysis for cycle 2026-2, tingxu202606, prefix Ib1202, with suffix ranging from 1 to 42, using rigaku3m_qmap_S270_D27_lin.hdf as the qmap.

#### Prompt 2:

Run Twotime analysis for cycle 2026-2, foster202606, prefix from F1173 to F1179, using designated qmaps for each measurement.



## Supported Tools

### XPCS

- `run_xpcs_boost_corr` - Submit a compute function that executes the `boost_corr` executable
  using a list of `raw` files and a shared `qmap` input; returns task UUIDs for each job.
  Poll them with `globus_compute_get_task_status`.
- `get_boost_corr_metadata` - Generate metadata from a `boost_corr` output HDF file
- `get_generic_metadata` - Read all HDF5 attributes from an output file in a JSON-serializable format
- `list_xpcs_collections` - List configured XPCS collections and allowed basepaths/permissions
- `list_xpcs_compute_endpoints` - List configured XPCS compute endpoints and allowed basepaths/permissions

### [Globus Transfer](https://docs.globus.org/api/transfer/)

- `globus_transfer_list_endpoints_and_collections` - List endpoints and collections the user can access
- `globus_transfer_search_endpoints_and_collections` - Search visible endpoints and collections
- `globus_transfer_submit_task` - Submit a transfer task, await completion/timeout, and return status plus recent events
- `globus_transfer_get_task_events` - Get task events for transfer progress and troubleshooting
- `globus_transfer_get_task_progress` - Wait for transfer progress and return task status plus recent events
- `globus_transfer_list_directory` - List directory contents on a collection; `filename_regex`
  filtering applies before `limit` and `offset` pagination

Notes:
- `globus_transfer_list_directory` applies `filename_regex` before pagination, so narrow queries can
  still return matches without raising `limit`.
This README intentionally documents only XPCS and Transfer tools. Compute service tools are omitted.

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
        "xpcs",
        "transfer"
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