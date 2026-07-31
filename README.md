# Discord MCP Server

[![smithery badge](https://smithery.ai/badge/@hanweg/mcp-discord)](https://smithery.ai/server/@hanweg/mcp-discord)
A Model Context Protocol (MCP) server that provides Discord integration capabilities to MCP clients like Claude Desktop.

<a href="https://glama.ai/mcp/servers/wvwjgcnppa"><img width="380" height="200" src="https://glama.ai/mcp/servers/wvwjgcnppa/badge" alt="mcp-discord MCP server" /></a>

## Available Tools

### Server Information
- `list_servers`: List available servers
- `get_server_info`: Get detailed server information
- `get_channels`: List channels in a server
- `list_members`: List server members and their roles
- `get_user_info`: Get detailed information about a user

### Message Management
- `send_message`: Send a message to a channel
- `read_messages`: Read recent message history
- `add_reaction`: Add a reaction to a message
- `add_multiple_reactions`: Add multiple reactions to a message
- `remove_reaction`: Remove a reaction from a message
- `moderate_message`: Delete messages and timeout users

### Channel Management
- `create_text_channel`: Create a new text channel
- `delete_channel`: Delete an existing channel

### Role Management
- `add_role`: Add a role to a user
- `remove_role`: Remove a role from a user

## Installation

1. Set up your Discord bot:
   - Create a new application at [Discord Developer Portal](https://discord.com/developers/applications)
   - Create a bot and copy the token
   - Enable required privileged intents:
     - MESSAGE CONTENT INTENT
     - SERVER MEMBERS INTENT
   - Invite the bot to your server using OAuth2 URL Generator

2. Clone and install the package:
```bash
# Clone the repository
git clone https://github.com/omniscoder/mcp-discord.git
cd mcp-discord

# Install the locked application and development dependencies
uv sync --frozen
```

3. Configure Claude Desktop (`%APPDATA%\Claude\claude_desktop_config.json` on Windows, `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):
```json
{
  "mcpServers": {
    "discord": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\PATH\\TO\\mcp-discord",
        "run",
        "mcp-discord"
      ],
      "env": {
        "DISCORD_TOKEN": "your_bot_token",
        "DISCORD_ALLOWED_GUILD_IDS": "123456789012345678"
      }
    }
  }
}
```

## Safety configuration

The bot can read and write Discord data using its configured Discord permissions. Restrict those
permissions to the minimum needed and use `DISCORD_ALLOWED_GUILD_IDS` to limit the MCP server to a
comma-separated list of server IDs. If the variable is omitted, every server available to the bot is
accessible.

Administrative tools (`add_role`, `remove_role`, `create_text_channel`, `delete_channel`, and
`moderate_message`) are hidden and rejected by default. Set `DISCORD_ENABLE_ADMIN_TOOLS=true` only
when those operations are intentionally required. Outgoing messages suppress all user, role, and
`@everyone` mentions by default.

Optional configuration:

- `DISCORD_READY_TIMEOUT_SECONDS`: seconds to wait for Discord login, default `30`.
- `DISCORD_ALLOWED_GUILD_IDS`: comma-separated server IDs.
- `DISCORD_ENABLE_ADMIN_TOOLS`: set to `true` to expose administrative tools.

For Docker, pass the token at runtime rather than storing it in the image:

```bash
docker run --rm -i -e DISCORD_TOKEN -e DISCORD_ALLOWED_GUILD_IDS mcp-discord
```

### Installing via Smithery

To install Discord Server for Claude Desktop automatically via [Smithery](https://smithery.ai/server/@hanweg/mcp-discord):

```bash
npx -y @smithery/cli install @hanweg/mcp-discord --client claude
```

## License

MIT License - see LICENSE file for details.
