# Nexus MCP

A [Model Context Protocol](https://modelcontextprotocol.io) server that
exposes read-only admin queries against a running Nexus backend to MCP
clients (Claude Desktop, or any other MCP-compatible client).

## Security model

- **Read-only by design.** The tool surface is `list_users`, `get_user`,
  `list_posts`, and `get_stats` — there is no delete, write, or moderation
  tool of any kind. This is enforced by test coverage
  (`src/tools.test.ts`), not just convention.
- **Scoped credential only.** Configure this server with the backend's
  `SERVICE_TOKEN_READ` value — never `SERVICE_TOKEN_NOTIFY`,
  `SERVICE_TOKEN_DELETE`, or the deprecated all-scopes `ADMIN_SERVICE_TOKEN`.
  A read-scoped token cannot perform notify or delete operations even if a
  future tool were added to call them.
- **HTTPS required by default.** `NEXUS_API_BASE_URL` must be `https://`
  unless it is `localhost`/`127.0.0.1`/`::1`, or an internal hostname you've
  explicitly listed in `NEXUS_MCP_ALLOWED_HTTP_HOSTS` (e.g. a Docker Compose
  service name reachable only on a private network). A remote `http://` host
  is rejected outright.
- **No embedded userinfo.** A base URL containing credentials
  (`https://user:pass@host`) is rejected, including on an otherwise-allowed
  loopback host.

See the main [README's Security Features](../README.md#security-features)
and [SECURITY.md](../SECURITY.md) for how this fits into Nexus as a whole.

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp nexus-mcp/.env.example nexus-mcp/.env
```

| Variable | Required | Notes |
|---|---|---|
| `NEXUS_API_BASE_URL` | yes | Base URL of the Nexus backend's admin API. |
| `NEXUS_SERVICE_TOKEN` | yes | Issue this server a `SERVICE_TOKEN_READ` value only. |
| `NEXUS_MCP_ALLOWED_HTTP_HOSTS` | no | Comma-separated internal hostnames allowed to use `http://`. Leave unset unless you know you need it. |

## Build and run

```bash
npm install
npm run build
npm start
```

## Connecting an MCP client

`claude_desktop_config.example.json` shows the shape of a client
configuration entry — copy it into your MCP client's own config file and
replace the placeholder path, URL, and token with your real values. Never
commit a filled-in copy of this file; it contains a service credential.

## Tests

```bash
npm test
```
