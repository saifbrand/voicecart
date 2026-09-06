"""Who gets told the basket changed, and who does not.

The delivery is proved end to end over HTTP in test_mcp_session.py. What is
covered here is the part that is easy to get quietly wrong: whether the
server admits it can be subscribed to at all, and whether the thing it keys
a subscription on survives longer than one request.
"""
from __future__ import annotations

import pytest
from mcp.server.mcpserver import MCPServer

from voicecart import server as voicecart_server
from voicecart import subscriptions

LEGACY = "2025-11-25"


@pytest.fixture(autouse=True)
def no_leftover_subscribers():
    subscriptions.forget_all()
    yield
    subscriptions.forget_all()


def capabilities_of(server: MCPServer, version: str):
    return server._lowlevel_server.get_capabilities(protocol_version=version)


def test_the_shop_tells_a_2025_client_it_can_subscribe():
    """The whole reason for installing a handler: a client asks first."""
    resources = capabilities_of(voicecart_server.server, LEGACY).resources
    assert resources is not None and resources.subscribe is True


def test_without_that_handler_the_sdk_would_have_said_no():
    """Documents the gap, so a future SDK closing it is visible here first."""
    bare = MCPServer(name="bare")

    @bare.resource("shop://nothing", name="Nothing", mime_type="text/plain")
    def nothing() -> str:
        return ""

    resources = capabilities_of(bare, LEGACY).resources
    assert resources is not None and resources.subscribe is False


# --- keying a subscription -------------------------------------------------

class FakeHeaders(dict):
    pass


class FakeRequest:
    def __init__(self, session_id: str | None):
        self.headers = FakeHeaders(
            {subscriptions.SESSION_HEADER: session_id} if session_id else {}
        )


class FakeContext:
    """Shaped like the low-level context a subscribe handler is handed."""

    def __init__(self, session_id: str | None = None, session=None):
        self.request = FakeRequest(session_id)
        self.session = session or object()


def test_the_key_is_the_transport_session_not_the_request():
    """Two requests, two session objects, one client - one key.

    This is the bug the whole module exists around: keying on the
    `ServerSession` looks right and drops every notification, because
    Streamable HTTP builds a new one per request.
    """
    subscribed = FakeContext("abc-123")
    later = FakeContext("abc-123")

    assert subscribed.session is not later.session
    assert subscriptions.session_key(subscribed) == subscriptions.session_key(later)


def test_a_client_only_hears_about_what_it_asked_for():
    key = "abc-123"
    subscriptions.subscribe(key, subscriptions.cart_uri("ayesha"))

    assert subscriptions.is_subscribed(key, "shop://cart/ayesha")
    assert not subscriptions.is_subscribed(key, "shop://cart/someone-else")
    assert not subscriptions.is_subscribed("another-session", "shop://cart/ayesha")


def test_unsubscribing_is_heard():
    key = "abc-123"
    uri = subscriptions.cart_uri("ayesha")
    subscriptions.subscribe(key, uri)
    subscriptions.unsubscribe(key, uri)

    assert not subscriptions.is_subscribed(key, uri)


def test_a_session_with_no_id_is_never_a_subscriber():
    """A key that cannot identify anybody must not become everybody's key."""
    assert subscriptions.session_key(None) == ""
    subscriptions.subscribe("", "shop://cart/ayesha")
    assert not subscriptions.is_subscribed("", "shop://cart/ayesha")


def test_the_oldest_subscribers_are_dropped_rather_than_grown_forever():
    for index in range(subscriptions.MAX_SESSIONS + 10):
        subscriptions.subscribe(f"session-{index}", "shop://cart/x")

    assert not subscriptions.is_subscribed("session-0", "shop://cart/x")
    assert subscriptions.is_subscribed(
        f"session-{subscriptions.MAX_SESSIONS + 9}", "shop://cart/x"
    )
