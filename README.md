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

The main supported tool is the xpcs Boost Corr tool below. The transfer tools support stanging data and moving it
into place so the boost corr work can be carried out, and results can be transferred back to voyager.

Let us know if you want other boost corr tooling!

### XPCS

- `run_xpcs_boost_corr` - Submit a compute function that executes the `boost_corr` executable
  using one `raw` file and a shared `qmap` input; returns `task_id` and `task_group_id`
  from the submitted compute job.

### [Globus Transfer](https://docs.globus.org/api/transfer/)

- `globus_transfer_submit_task` - Submit a transfer task, await completion/timeout, and return status plus recent events
- `globus_transfer_get_task_events` - Get task events for transfer progress and troubleshooting
- `globus_transfer_get_task_progress` - Wait for transfer progress and return task status plus recent events
- `globus_transfer_list_directory` - List directory contents on a collection; `filename_regex`
  filtering applies before `limit` and `offset` pagination; `cached` defaults to `true`
  and can be set to `false` to force a fresh listing
- `list_xpcs_collections` - List configured XPCS collections and allowed basepaths/permissions

### Globus Compute

- `list_xpcs_compute_endpoints` - List configured XPCS compute endpoints and allowed basepaths/permissions
- `globus_compute_get_task_status` - Get status of current compute tasks started with run_xpcs_boost_corr
- `globus_compute_get_endpoint_status` - Get the status of a configured Globus Compute Endpoint
- `globus_compute_get_endpoint_metadata` - Get endpoint metadata of a configured Globus Compute Endpoint

## Client Configuration

The following configuration is compatible with most LLM applications that support MCP such as
[Claude Desktop](https://modelcontextprotocol.io/docs/develop/connect-local-servers):

```json
{
  "mcpServers": {
    "globus-mcp-xpcs": {
      "type": "http", 
      "url": "http://127.0.0.1:8000/mcp"
    }
  },
}
```

## Server Configuration

Install the latest server (supports Python 3.12 or later), set your secrets,
and run the service:

```
pip install globus-mcp-server
export GLOBUS_CLIENT_ID="my-client-id"
export GLOBUS_CLIENT_SECRET="my-client-secret"
globus-mcp-xpcs
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
      "args": ["globus-mcp-xpcs", "--transport", "stdio"],
      "env": {
        "GLOBUS_CLIENT_ID": "...",
        "GLOBUS_CLIENT_SECRET": "..."
      }
    }
  }
}
```