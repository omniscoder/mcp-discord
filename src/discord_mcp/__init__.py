"""Discord integration for Model Context Protocol."""

import asyncio
import logging
import warnings

from . import server

__version__ = "0.1.0"


def main():
    """Main entry point for the package."""
    # Suppress PyNaCl warning since we don't use voice features
    warnings.filterwarnings("ignore", module="discord.client", message="PyNaCl is not installed")

    try:
        asyncio.run(server.main())
    except KeyboardInterrupt:
        logging.getLogger("discord-mcp-server").info("Shutting down Discord MCP server")
    except Exception:
        logging.getLogger("discord-mcp-server").exception(
            "Discord MCP server stopped with an error"
        )
        raise


# Expose important items at package level
__all__ = ["main", "server"]
