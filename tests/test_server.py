import json

import pytest

from discord_mcp import server


class FakeGuild:
    def __init__(self, guild_id=123):
        self.id = guild_id


class FakeMessage:
    def __init__(self, author=None):
        self.id = 456
        self.author = author
        self.deleted = False
        self.delete_reason = None

    async def delete(self, *, reason):
        self.deleted = True
        self.delete_reason = reason


class FakeChannel:
    def __init__(self, guild_id=123, message=None):
        self.guild = FakeGuild(guild_id)
        self.message = message or FakeMessage()
        self.sent = []

    async def send(self, content, **kwargs):
        self.sent.append((content, kwargs))
        return FakeMessage()

    async def fetch_message(self, _message_id):
        return self.message


class FakeClient:
    def __init__(self, channel):
        self.channel = channel
        self.user = object()

    def is_ready(self):
        return True

    async def fetch_channel(self, _channel_id):
        return self.channel


@pytest.fixture
def install_client(monkeypatch):
    def _install(channel):
        monkeypatch.setattr(server, "discord_client", FakeClient(channel))
        return channel

    return _install


def result_json(result):
    return json.loads(result[0].text)


def test_id_and_limit_validation():
    assert server._as_id({"server_id": "123"}, "server_id") == 123
    assert server._bounded_int({}, "limit", 10, 100) == 10

    with pytest.raises(ValueError, match="positive"):
        server._as_id({"server_id": "0"}, "server_id")
    with pytest.raises(ValueError, match="between 1 and 100"):
        server._bounded_int({"limit": -1}, "limit", 10, 100)


def test_guild_allowlist(monkeypatch):
    monkeypatch.setenv("DISCORD_ALLOWED_GUILD_IDS", "123,456")
    server._ensure_guild_allowed(123)

    with pytest.raises(PermissionError, match="not in DISCORD_ALLOWED_GUILD_IDS"):
        server._ensure_guild_allowed(789)


@pytest.mark.asyncio
async def test_admin_tools_hidden_by_default(monkeypatch):
    monkeypatch.delenv("DISCORD_ENABLE_ADMIN_TOOLS", raising=False)
    names = {tool.name for tool in await server.list_tools()}
    assert names.isdisjoint(server.ADMIN_TOOL_NAMES)

    monkeypatch.setenv("DISCORD_ENABLE_ADMIN_TOOLS", "true")
    names = {tool.name for tool in await server.list_tools()}
    assert server.ADMIN_TOOL_NAMES <= names


@pytest.mark.asyncio
async def test_send_message_suppresses_mentions(install_client, monkeypatch):
    monkeypatch.delenv("DISCORD_ALLOWED_GUILD_IDS", raising=False)
    channel = install_client(FakeChannel())

    result = await server.call_tool(
        "send_message",
        {"channel_id": "123", "content": "hello @everyone"},
    )

    assert result_json(result) == {"ok": True, "message_id": "456"}
    _, kwargs = channel.sent[0]
    allowed_mentions = kwargs["allowed_mentions"]
    assert allowed_mentions.everyone is False
    assert allowed_mentions.roles is False
    assert allowed_mentions.users is False


@pytest.mark.asyncio
async def test_send_message_rejects_disallowed_guild(install_client, monkeypatch):
    monkeypatch.setenv("DISCORD_ALLOWED_GUILD_IDS", "999")
    install_client(FakeChannel(guild_id=123))

    with pytest.raises(PermissionError, match="not in DISCORD_ALLOWED_GUILD_IDS"):
        await server.call_tool("send_message", {"channel_id": "123", "content": "hello"})


@pytest.mark.asyncio
async def test_moderation_timeout_uses_timedelta(install_client, monkeypatch):
    class FakeMember:
        def __init__(self):
            self.timeout_until = None
            self.timeout_reason = None

        async def timeout(self, until, *, reason):
            self.timeout_until = until
            self.timeout_reason = reason

    author = FakeMember()
    message = FakeMessage(author=author)
    install_client(FakeChannel(message=message))
    monkeypatch.setattr(server.discord, "Member", FakeMember)
    monkeypatch.setenv("DISCORD_ENABLE_ADMIN_TOOLS", "true")
    monkeypatch.delenv("DISCORD_ALLOWED_GUILD_IDS", raising=False)

    await server.call_tool(
        "moderate_message",
        {
            "channel_id": "123",
            "message_id": "456",
            "reason": "test moderation",
            "timeout_minutes": 5,
        },
    )

    assert message.deleted is True
    assert message.delete_reason == "test moderation"
    assert author.timeout_until is not None
    assert author.timeout_reason == "test moderation"


@pytest.mark.asyncio
async def test_admin_handler_rejects_direct_calls(install_client, monkeypatch):
    install_client(FakeChannel())
    monkeypatch.delenv("DISCORD_ENABLE_ADMIN_TOOLS", raising=False)

    with pytest.raises(PermissionError, match="disabled"):
        await server.call_tool("delete_channel", {"channel_id": "123"})
