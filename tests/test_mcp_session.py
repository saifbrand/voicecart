"""The real thing: a shopping trip over MCP Streamable HTTP.

This starts the server as its own process and drives it with the MCP client,
so what is exercised here is the transport, the negotiated protocol version,
the tool schemas and the shop rules together. If this passes, an assistant
speaking MCP can shop this store.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_PROTOCOL = "2025-11-25"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def endpoint(tmp_path_factory):
    """A server process with its own throwaway cart and order files."""
    port = free_port()
    state = tmp_path_factory.mktemp("state")

    env = {**os.environ, "HOST": "127.0.0.1", "PORT": str(port),
           "VOICECART_STATE_DIR": str(state)}
    process = subprocess.Popen(
        [sys.executable, "-m", "voicecart.server"],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    url = f"http://127.0.0.1:{port}/mcp"
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                break
        except OSError:
            time.sleep(0.25)
    else:
        process.kill()
        pytest.fail("the server never came up")

    yield url
    process.terminate()
    process.wait(timeout=10)


async def speak(session: ClientSession, tool: str, **args) -> dict:
    result = await session.call_tool(tool, args)
    assert result.structured_content is not None, f"{tool} returned no structured output"
    return result.structured_content


@pytest.mark.anyio
async def test_a_whole_shopping_trip_over_streamable_http(endpoint):
    async with streamable_http_client(endpoint) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()

            # The track requires this version or later.
            assert init.protocol_version >= REQUIRED_PROTOCOL
            assert init.server_info.name == "voicecart"

            tools = {tool.name for tool in (await session.list_tools()).tools}
            assert {"search_products", "add_to_cart", "review_order",
                    "place_order", "order_status"} <= tools

            found = await speak(session, "search_products", query="honey")
            assert found["cards"], "a search should come back with something to show"
            sku = found["cards"][0]["sku"]

            added = await speak(session, "add_to_cart", sku=sku, quantity=1)
            assert added["ok"] and added["cart_total"] > 0

            # An order is never placed on the first ask.
            refused = await speak(session, "place_order", address="House 12, Dhanmondi")
            assert refused["ok"] is False
            assert refused["needs_confirmation"] is True

            review = await speak(session, "review_order", address="House 12, Dhanmondi")
            assert "cash" in review["speech"]
            assert "House 12, Dhanmondi" in review["speech"]

            placed = await speak(session, "place_order",
                                 address="House 12, Dhanmondi", confirmed=True)
            assert placed["ok"] and placed["order_id"]

            # The basket empties, and the order can be found again by voice.
            assert (await speak(session, "read_cart"))["line_count"] == 0
            status = await speak(session, "order_status")
            assert status["order_id"] == placed["order_id"]

            # And "the usual" now means something.
            again = await speak(session, "reorder_last")
            assert again["ok"] and again["cart_total"] > 0


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"
