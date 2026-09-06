"""Telling a client the basket changed, instead of making it ask.

`shop://cart/{shopper_id}` is a resource, so a client can read the basket
without calling a tool. But a resource that has to be re-read to be trusted
is only half of one: a screen showing the basket goes stale the moment
anything changes, and the client has no way to know it has.

The protocol's answer is `resources/subscribe` and the `resources/updated`
notification, and this is the piece that wires it up.

Two eras have to be served at once, and they disagree:

* **2025-11-25** - the version this track requires, and the one this server
  actually negotiates - a client calls `resources/subscribe` with a URI and
  the server sends `notifications/resources/updated` for it. A server only
  advertises `resources.subscribe` at all if it serves that method.
* **2026-07-28 and later** - subscriptions moved to a single
  `subscriptions/listen` stream, which the SDK's `MCPServer` serves for
  free, and events go out through `ctx.notify_resource_updated`.

The SDK handles the second on its own and nothing at all for the first: the
high-level server never registers a `resources/subscribe` handler, so at
2025-11-25 it advertises `subscribe: false` and no client on that version
would ever ask. Registering one here closes that gap.

**The catch worth knowing about.** The obvious way to remember who
subscribed is to key on the `ServerSession` the handler is handed. That is
wrong: over Streamable HTTP a fresh `ServerSession` is built per request, so
the object that subscribes is not the object that later adds to the basket,
and every notification is silently dropped. The only thing that survives
across requests is the transport's own `Mcp-Session-Id`, so that is the key.
It is a plain string with no lifetime of its own, hence the cap below.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any

from mcp import types

SESSION_HEADER = "mcp-session-id"

# Subscriptions are held per MCP session. A string key cannot be weakly
# referenced, so rather than leak an entry for every client that ever
# connects, the oldest are dropped: a forgotten subscription stops being
# notified, which is a far smaller problem than a server that grows forever.
MAX_SESSIONS = 512

_SUBSCRIBED: "OrderedDict[str, set[str]]" = OrderedDict()


def cart_uri(shopper_id: str) -> str:
    return f"shop://cart/{shopper_id}"


def session_key(ctx: Any) -> str:
    """What identifies this client across requests.

    Handed either a low-level `ServerRequestContext` or a tool's `Context`;
    both reach the HTTP request, one directly and one through
    `request_context`.
    """
    if ctx is None:
        return ""

    request = getattr(ctx, "request", None)
    if request is None:
        request = getattr(getattr(ctx, "request_context", None), "request", None)

    headers = getattr(request, "headers", None)
    if headers is not None:
        found = headers.get(SESSION_HEADER)
        if found:
            return str(found)

    # No HTTP request behind this call - stdio, or a test driving the tools
    # directly. One connection, so one key.
    session = getattr(ctx, "session", None)
    return f"connection-{id(session)}" if session is not None else ""


def subscribe(key: str, uri: str) -> None:
    if not key:
        return
    _SUBSCRIBED.setdefault(key, set()).add(uri)
    _SUBSCRIBED.move_to_end(key)
    while len(_SUBSCRIBED) > MAX_SESSIONS:
        _SUBSCRIBED.popitem(last=False)


def unsubscribe(key: str, uri: str) -> None:
    _SUBSCRIBED.get(key, set()).discard(uri)


def is_subscribed(key: str, uri: str) -> bool:
    return bool(key) and uri in _SUBSCRIBED.get(key, set())


def forget_all() -> None:
    """Only for tests, so one does not inherit another's subscribers."""
    _SUBSCRIBED.clear()


def install(server: Any) -> None:
    """Serve `resources/subscribe`, so 2025-11-25 clients can use it.

    Registered against the low-level server because the high-level one has
    no seam for it. Capabilities are derived from the handlers that exist,
    so this is also what makes the server advertise `resources.subscribe`
    to a client on that version.
    """
    lowlevel = server._lowlevel_server  # noqa: SLF001 - no public seam for this

    async def on_subscribe(ctx, params: types.SubscribeRequestParams) -> dict:
        subscribe(session_key(ctx), str(params.uri))
        return {}

    async def on_unsubscribe(ctx, params: types.UnsubscribeRequestParams) -> dict:
        unsubscribe(session_key(ctx), str(params.uri))
        return {}

    lowlevel.add_request_handler(
        "resources/subscribe", types.SubscribeRequestParams, on_subscribe
    )
    lowlevel.add_request_handler(
        "resources/unsubscribe", types.UnsubscribeRequestParams, on_unsubscribe
    )


async def cart_changed(ctx: Any, shopper_id: str) -> None:
    """Say that this shopper's basket is no longer what it was.

    Sent both ways, because the two protocol eras listen in different
    places, and neither is allowed to cost the shopper their basket: a
    notification that cannot be delivered is not a reason to fail a change
    that has already been made.
    """
    if ctx is None:
        return
    uri = cart_uri(shopper_id)

    try:
        await ctx.notify_resource_updated(uri)
    except Exception:  # noqa: BLE001 - a stream nobody is on is not an error
        pass

    session = getattr(ctx, "session", None)
    if session is not None and is_subscribed(session_key(ctx), uri):
        try:
            await session.send_resource_updated(uri)
        except Exception:  # noqa: BLE001
            pass
