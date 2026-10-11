import asyncio
import contextlib
import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import timedelta
from functools import wraps
from typing import Any

import discord
from discord.ext import commands
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("discord-mcp-server")

ADMIN_TOOL_NAMES = {
    "add_role",
    "remove_role",
    "create_text_channel",
    "delete_channel",
    "moderate_message",
}


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _allowed_guild_ids() -> set[int] | None:
    raw_value = os.getenv("DISCORD_ALLOWED_GUILD_IDS", "").strip()
    if not raw_value:
        return None
    try:
        return {int(value.strip()) for value in raw_value.split(",") if value.strip()}
    except ValueError as exc:
        raise ValueError(
            "DISCORD_ALLOWED_GUILD_IDS must contain comma-separated Discord IDs"
        ) from exc


def _ensure_guild_allowed(guild_id: int) -> None:
    allowed_ids = _allowed_guild_ids()
    if allowed_ids is not None and guild_id not in allowed_ids:
        raise PermissionError(f"Discord server {guild_id} is not in DISCORD_ALLOWED_GUILD_IDS")


def _require_admin_tools(name: str) -> None:
    if name in ADMIN_TOOL_NAMES and not _env_flag("DISCORD_ENABLE_ADMIN_TOOLS"):
        raise PermissionError(
            f"{name} is disabled; set DISCORD_ENABLE_ADMIN_TOOLS=true "
            "to enable administrative tools"
        )


def _as_id(arguments: dict[str, Any], key: str) -> int:
    try:
        value = int(arguments[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a valid Discord ID") from exc
    if value <= 0:
        raise ValueError(f"{key} must be a positive Discord ID")
    return value


def _bounded_int(arguments: dict[str, Any], key: str, default: int, maximum: int) -> int:
    try:
        value = int(arguments.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if not 1 <= value <= maximum:
        raise ValueError(f"{key} must be between 1 and {maximum}")
    return value


def _text_result(payload: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, default=str))]


# Initialize Discord bot with necessary intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Initialize MCP server
app = Server("discord-server")

# Keep one client reference that tests can replace without changing the configured bot.
discord_client = bot


@bot.event
async def on_ready():
    logger.info("Logged in as %s", bot.user)


# Helper function to ensure Discord client is ready
def require_discord_client(func: Callable[..., Awaitable[list[TextContent]]]):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        if not discord_client or not discord_client.is_ready():
            raise RuntimeError("Discord client not ready")
        return await func(*args, **kwargs)

    return wrapper


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available Discord tools."""
    tools = [
        # Server Information Tools
        Tool(
            name="get_server_info",
            description="Get information about a Discord server",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {"type": "string", "description": "Discord server (guild) ID"}
                },
                "required": ["server_id"],
            },
        ),
        Tool(
            name="get_channels",
            description="Get a list of all channels in a Discord server",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {"type": "string", "description": "Discord server (guild) ID"}
                },
                "required": ["server_id"],
            },
        ),
        Tool(
            name="list_members",
            description="Get a list of members in a server",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {"type": "string", "description": "Discord server (guild) ID"},
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of members to fetch",
                        "minimum": 1,
                        "maximum": 1000,
                    },
                },
                "required": ["server_id"],
            },
        ),
        # Role Management Tools
        Tool(
            name="add_role",
            description="Add a role to a user",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {"type": "string", "description": "Discord server ID"},
                    "user_id": {"type": "string", "description": "User to add role to"},
                    "role_id": {"type": "string", "description": "Role ID to add"},
                },
                "required": ["server_id", "user_id", "role_id"],
            },
        ),
        Tool(
            name="remove_role",
            description="Remove a role from a user",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {"type": "string", "description": "Discord server ID"},
                    "user_id": {"type": "string", "description": "User to remove role from"},
                    "role_id": {"type": "string", "description": "Role ID to remove"},
                },
                "required": ["server_id", "user_id", "role_id"],
            },
        ),
        # Channel Management Tools
        Tool(
            name="create_text_channel",
            description="Create a new text channel",
            inputSchema={
                "type": "object",
                "properties": {
                    "server_id": {"type": "string", "description": "Discord server ID"},
                    "name": {"type": "string", "description": "Channel name"},
                    "category_id": {
                        "type": "string",
                        "description": "Optional category ID to place channel in",
                    },
                    "topic": {"type": "string", "description": "Optional channel topic"},
                },
                "required": ["server_id", "name"],
            },
        ),
        Tool(
            name="delete_channel",
            description="Delete a channel",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string", "description": "ID of channel to delete"},
                    "reason": {"type": "string", "description": "Reason for deletion"},
                },
                "required": ["channel_id"],
            },
        ),
        # Message Reaction Tools
        Tool(
            name="add_reaction",
            description="Add a reaction to a message",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "Channel containing the message",
                    },
                    "message_id": {"type": "string", "description": "Message to react to"},
                    "emoji": {
                        "type": "string",
                        "description": "Emoji to react with (Unicode or custom emoji ID)",
                    },
                },
                "required": ["channel_id", "message_id", "emoji"],
            },
        ),
        Tool(
            name="add_multiple_reactions",
            description="Add multiple reactions to a message",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "Channel containing the message",
                    },
                    "message_id": {"type": "string", "description": "Message to react to"},
                    "emojis": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "description": "Emoji to react with (Unicode or custom emoji ID)",
                        },
                        "description": "List of emojis to add as reactions",
                        "minItems": 1,
                        "maxItems": 20,
                        "uniqueItems": True,
                    },
                },
                "required": ["channel_id", "message_id", "emojis"],
            },
        ),
        Tool(
            name="remove_reaction",
            description="Remove a reaction from a message",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "Channel containing the message",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message to remove reaction from",
                    },
                    "emoji": {
                        "type": "string",
                        "description": "Emoji to remove (Unicode or custom emoji ID)",
                    },
                },
                "required": ["channel_id", "message_id", "emoji"],
            },
        ),
        Tool(
            name="send_message",
            description="Send a message to a specific channel",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string", "description": "Discord channel ID"},
                    "content": {
                        "type": "string",
                        "description": "Message content",
                        "minLength": 1,
                        "maxLength": 2000,
                    },
                },
                "required": ["channel_id", "content"],
            },
        ),
        Tool(
            name="read_messages",
            description="Read recent messages from a channel",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string", "description": "Discord channel ID"},
                    "limit": {
                        "type": "integer",
                        "description": "Number of messages to fetch (max 100)",
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": ["channel_id"],
            },
        ),
        Tool(
            name="get_user_info",
            description="Get information about a Discord user",
            inputSchema={
                "type": "object",
                "properties": {"user_id": {"type": "string", "description": "Discord user ID"}},
                "required": ["user_id"],
            },
        ),
        Tool(
            name="moderate_message",
            description="Delete a message and optionally timeout the user",
            inputSchema={
                "type": "object",
                "properties": {
                    "channel_id": {
                        "type": "string",
                        "description": "Channel ID containing the message",
                    },
                    "message_id": {"type": "string", "description": "ID of message to moderate"},
                    "reason": {"type": "string", "description": "Reason for moderation"},
                    "timeout_minutes": {
                        "type": "integer",
                        "description": "Optional timeout duration in minutes",
                        "minimum": 0,
                        "maximum": 40320,  # Max 4 weeks
                    },
                },
                "required": ["channel_id", "message_id", "reason"],
            },
        ),
        Tool(
            name="list_servers",
            description=(
                "Get all Discord servers available to the bot, including their IDs, "
                "member counts, and creation dates."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
    ]
    if not _env_flag("DISCORD_ENABLE_ADMIN_TOOLS"):
        tools = [tool for tool in tools if tool.name not in ADMIN_TOOL_NAMES]
    return tools


@app.call_tool()
@require_discord_client
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle Discord tool calls."""
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object")
    _require_admin_tools(name)

    if name == "send_message":
        channel = await _fetch_channel(_as_id(arguments, "channel_id"))
        content = arguments.get("content")
        if not isinstance(content, str) or not 1 <= len(content) <= 2000:
            raise ValueError("content must contain between 1 and 2000 characters")
        message = await channel.send(
            content,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return _text_result({"ok": True, "message_id": str(message.id)})

    elif name == "read_messages":
        channel = await _fetch_channel(_as_id(arguments, "channel_id"))
        limit = _bounded_int(arguments, "limit", 10, 100)
        messages = []
        async for message in channel.history(limit=limit):
            reaction_data = []
            for reaction in message.reactions:
                emoji_str = (
                    str(reaction.emoji.name)
                    if hasattr(reaction.emoji, "name") and reaction.emoji.name
                    else str(reaction.emoji.id)
                    if hasattr(reaction.emoji, "id")
                    else str(reaction.emoji)
                )
                reaction_info = {"emoji": emoji_str, "count": reaction.count}
                reaction_data.append(reaction_info)
            messages.append(
                {
                    "id": str(message.id),
                    "author": str(message.author),
                    "content": message.content,
                    "timestamp": message.created_at.isoformat(),
                    "reactions": reaction_data,  # Add reactions to message dict
                }
            )
        return _text_result({"count": len(messages), "messages": messages})

    elif name == "get_user_info":
        user = await discord_client.fetch_user(_as_id(arguments, "user_id"))
        user_info = {
            "id": str(user.id),
            "name": user.name,
            "discriminator": user.discriminator,
            "bot": user.bot,
            "created_at": user.created_at.isoformat(),
        }
        return _text_result(user_info)

    elif name == "moderate_message":
        channel = await _fetch_channel(_as_id(arguments, "channel_id"))
        message = await channel.fetch_message(_as_id(arguments, "message_id"))
        reason = arguments.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")

        try:
            timeout_minutes = int(arguments.get("timeout_minutes", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout_minutes must be an integer") from exc
        if not 0 <= timeout_minutes <= 40320:
            raise ValueError("timeout_minutes must be between 0 and 40320")

        # Delete the message
        await message.delete(reason=reason)

        # Handle timeout if specified
        if timeout_minutes > 0:
            if isinstance(message.author, discord.Member):
                duration = discord.utils.utcnow() + timedelta(minutes=timeout_minutes)
                await message.author.timeout(duration, reason=reason)
                return [
                    TextContent(
                        type="text",
                        text=f"Message deleted and user timed out for {timeout_minutes} minutes.",
                    )
                ]

        return [TextContent(type="text", text="Message deleted successfully.")]

    # Server Information Tools
    elif name == "get_server_info":
        guild = await _fetch_guild(_as_id(arguments, "server_id"))
        info = {
            "name": guild.name,
            "id": str(guild.id),
            "owner_id": str(guild.owner_id),
            "member_count": guild.member_count,
            "created_at": guild.created_at.isoformat(),
            "description": guild.description,
            "premium_tier": guild.premium_tier,
            "explicit_content_filter": str(guild.explicit_content_filter),
        }
        return [
            TextContent(
                type="text",
                text="Server Information:\n" + "\n".join(f"{k}: {v}" for k, v in info.items()),
            )
        ]

    elif name == "get_channels":
        guild_id = _as_id(arguments, "server_id")
        _ensure_guild_allowed(guild_id)
        guild = discord_client.get_guild(guild_id)
        if guild is None:
            guild = await _fetch_guild(guild_id)
            channels = await guild.fetch_channels()
        else:
            channels = guild.channels
        return _text_result(
            {
                "server_id": str(guild.id),
                "server_name": guild.name,
                "channels": [
                    {"id": str(channel.id), "name": channel.name, "type": str(channel.type)}
                    for channel in channels
                ],
            }
        )

    elif name == "list_members":
        guild = await _fetch_guild(_as_id(arguments, "server_id"))
        limit = _bounded_int(arguments, "limit", 100, 1000)

        members = []
        async for member in guild.fetch_members(limit=limit):
            members.append(
                {
                    "id": str(member.id),
                    "name": member.name,
                    "nick": member.nick,
                    "joined_at": member.joined_at.isoformat() if member.joined_at else None,
                    "roles": [str(role.id) for role in member.roles[1:]],  # Skip @everyone
                }
            )

        return [
            TextContent(
                type="text",
                text=f"Server Members ({len(members)}):\n"
                + "\n".join(
                    f"{m['name']} (ID: {m['id']}, Roles: {', '.join(m['roles'])})" for m in members
                ),
            )
        ]

    # Role Management Tools
    elif name == "add_role":
        guild = await _fetch_guild(_as_id(arguments, "server_id"))
        member = await guild.fetch_member(_as_id(arguments, "user_id"))
        role = guild.get_role(_as_id(arguments, "role_id"))
        if role is None:
            raise ValueError("Role not found in the requested server")

        await member.add_roles(role, reason="Role added via MCP")
        return [TextContent(type="text", text=f"Added role {role.name} to user {member.name}")]

    elif name == "remove_role":
        guild = await _fetch_guild(_as_id(arguments, "server_id"))
        member = await guild.fetch_member(_as_id(arguments, "user_id"))
        role = guild.get_role(_as_id(arguments, "role_id"))
        if role is None:
            raise ValueError("Role not found in the requested server")

        await member.remove_roles(role, reason="Role removed via MCP")
        return [TextContent(type="text", text=f"Removed role {role.name} from user {member.name}")]

    # Channel Management Tools
    elif name == "create_text_channel":
        guild = await _fetch_guild(_as_id(arguments, "server_id"))
        category = None
        if "category_id" in arguments:
            category = guild.get_channel(_as_id(arguments, "category_id"))
            if not isinstance(category, discord.CategoryChannel):
                raise ValueError("Category not found in the requested server")

        channel = await guild.create_text_channel(
            name=arguments["name"],
            category=category,
            topic=arguments.get("topic"),
            reason="Channel created via MCP",
        )

        return [
            TextContent(
                type="text", text=f"Created text channel #{channel.name} (ID: {channel.id})"
            )
        ]

    elif name == "delete_channel":
        channel = await _fetch_channel(_as_id(arguments, "channel_id"))
        await channel.delete(reason=arguments.get("reason", "Channel deleted via MCP"))
        return [TextContent(type="text", text="Deleted channel successfully")]

    # Message Reaction Tools
    elif name == "add_reaction":
        channel = await _fetch_channel(_as_id(arguments, "channel_id"))
        message = await channel.fetch_message(_as_id(arguments, "message_id"))
        await message.add_reaction(arguments["emoji"])
        return [TextContent(type="text", text=f"Added reaction {arguments['emoji']} to message")]

    elif name == "add_multiple_reactions":
        channel = await _fetch_channel(_as_id(arguments, "channel_id"))
        message = await channel.fetch_message(_as_id(arguments, "message_id"))
        emojis = arguments.get("emojis")
        if (
            not isinstance(emojis, list)
            or not 1 <= len(emojis) <= 20
            or any(not isinstance(emoji, str) or not emoji for emoji in emojis)
        ):
            raise ValueError("emojis must contain between 1 and 20 non-empty strings")
        if len(set(emojis)) != len(emojis):
            raise ValueError("emojis must not contain duplicates")
        for emoji in emojis:
            await message.add_reaction(emoji)
        return [TextContent(type="text", text=f"Added reactions: {', '.join(emojis)} to message")]

    elif name == "remove_reaction":
        channel = await _fetch_channel(_as_id(arguments, "channel_id"))
        message = await channel.fetch_message(_as_id(arguments, "message_id"))
        await message.remove_reaction(arguments["emoji"], discord_client.user)
        return [
            TextContent(type="text", text=f"Removed reaction {arguments['emoji']} from message")
        ]

    elif name == "list_servers":
        allowed_ids = _allowed_guild_ids()
        servers = []
        for guild in discord_client.guilds:
            if allowed_ids is not None and guild.id not in allowed_ids:
                continue
            servers.append(
                {
                    "id": str(guild.id),
                    "name": guild.name,
                    "member_count": guild.member_count,
                    "created_at": guild.created_at.isoformat(),
                }
            )

        return [
            TextContent(
                type="text",
                text=f"Available Servers ({len(servers)}):\n"
                + "\n".join(
                    f"{s['name']} (ID: {s['id']}, Members: {s['member_count']})" for s in servers
                ),
            )
        ]

    raise ValueError(f"Unknown tool: {name}")


async def _fetch_channel(channel_id: int):
    channel = await discord_client.fetch_channel(channel_id)
    guild = getattr(channel, "guild", None)
    if guild is None:
        raise ValueError("Direct-message channels are not supported")
    _ensure_guild_allowed(guild.id)
    return channel


async def _fetch_guild(guild_id: int):
    _ensure_guild_allowed(guild_id)
    return await discord_client.fetch_guild(guild_id)


async def _wait_for_discord(bot_task: asyncio.Task, timeout: float) -> None:
    ready_task = asyncio.create_task(bot.wait_until_ready())
    try:
        done, _ = await asyncio.wait(
            {bot_task, ready_task},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if bot_task in done:
            await bot_task
            raise RuntimeError("Discord client stopped before becoming ready")
        if ready_task not in done:
            raise TimeoutError(f"Discord client was not ready within {timeout:g} seconds")
    finally:
        if not ready_task.done():
            ready_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ready_task


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN environment variable is required")

    try:
        ready_timeout = float(os.getenv("DISCORD_READY_TIMEOUT_SECONDS", "30"))
    except ValueError as exc:
        raise ValueError("DISCORD_READY_TIMEOUT_SECONDS must be a number") from exc
    if ready_timeout <= 0:
        raise ValueError("DISCORD_READY_TIMEOUT_SECONDS must be positive")

    _allowed_guild_ids()
    bot_task = asyncio.create_task(bot.start(token), name="discord-client")
    try:
        await _wait_for_discord(bot_task, ready_timeout)
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options(),
            )
    finally:
        await bot.close()
        if not bot_task.done():
            bot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot_task


if __name__ == "__main__":
    asyncio.run(main())
