# Friction log

Every entry below cost real time while building VoiceCart. They are in the
order I hit them, with what I expected, what happened, and what I would
change. Nothing here is hypothetical.

Environment: Python 3.14 on Windows 11, `mcp` 2.1.1, MCP protocol 2025-11-25.

---

## 1. Every quick start online builds a class the SDK no longer has

**Task** Stand up a minimal MCP server.

**Steps** `pip install mcp`, then the first line of every example I could
find: `from mcp.server.fastmcp import FastMCP`.

**Expected** A server object.

**Actual**

```
ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x,
where FastMCP was renamed to MCPServer (from mcp.server.mcpserver import
MCPServer) and other APIs changed; see the migration guide at
https://py.sdk.modelcontextprotocol.io/v2/migration/ or pin 'mcp<2'.
```

**Severity** Low, and only because of that error message. It names the new
import, the reason, the migration guide and the pin. This is the best
failure I hit all week and I want to say so before I complain about
anything else: a rename that tells you what it renamed itself to costs
thirty seconds instead of an afternoon.

**Workaround** None needed.

**Suggestion** The friction is not the SDK, it is that `pip install mcp` now
disagrees with every tutorial, sample and blog post written before the
rename. A one-line "on 2.x this is `MCPServer`" banner on the docs landing
page would catch people who never see the exception because they are
reading rather than running.

---

## 2. Returning a plain dict silently produces no structured output

**Task** Have a tool return `{"speech": ..., "cards": [...]}` so the client
can read one field aloud and render the other.

**Steps** Wrote the tool with `-> dict`, called it from a client, read
`result.structured_content`.

**Expected** The dictionary.

**Actual** `structured_content` was `None`. The data was there, but only as
a JSON string inside `content[0].text`. No warning, no error, no hint. My
first client crashed on `None` and I assumed I had the transport wrong,
because a transport problem is what a null result usually means.

**Severity** Important. This is the difference between a client that can
render a product carousel and one that reads JSON out loud, and nothing
tells you which one you built.

**Workaround** Declare a Pydantic model as the return type. The SDK then
generates an output schema and populates `structured_content` correctly.

**Suggestion** Warn at registration time when a tool is annotated `-> dict`
or `-> Any`, the way the SDK already warns about duplicate tool names.
Something like "tool 'x' has no output schema; clients will receive text
only. Return a BaseModel or TypedDict for structured output." One line at
startup, and nobody loses an hour to a silent `None`.

---

## 3. camelCase in the docs, snake_case in the Python

**Task** Read the server name and protocol version after `initialize()`.

**Steps** `init.serverInfo.name`, copied from the specification, which is
correct for the wire format.

**Expected** The name.

**Actual** `AttributeError: 'InitializeResult' object has no attribute
'serverInfo'. Did you mean: 'server_info'?`

Then the same again, four more times, each in a different place:
`structuredContent` -> `structured_content`, `inputSchema` ->
`input_schema`, `uriTemplate` -> `uri_template`, `protocolVersion` ->
`protocol_version`.

**Severity** Low individually, Important cumulatively. Python should be
snake_case and the wire should be camelCase; both choices are right. The
cost is that the specification and the SDK read as if they disagree, and
you pay it once per attribute rather than once.

**Workaround** The `Did you mean` hints in the pydantic errors carried me
through every one, which is the only reason this is not rated higher.

**Suggestion** A short mapping table in the Python SDK docs, "spec field ->
attribute", would remove the whole class of it. It is five lines of
documentation against a mistake every Python user makes at least once.

---

## 4. The client helper renamed and changed arity at the same time

**Task** Connect a test client over Streamable HTTP.

**Steps** `from mcp.client.streamable_http import streamablehttp_client`,
then `async with streamablehttp_client(url) as (read, write, get_session_id)`.

**Expected** A connected transport.

**Actual** Two failures in a row. First `ImportError: cannot import name
'streamablehttp_client'`; it is `streamable_http_client` now. Then
`ValueError: not enough values to unpack (expected 3, got 2)`, because the
context manager no longer yields the session-id callback.

**Severity** Important, because the second one arrives wrapped in an anyio
`ExceptionGroup` from inside a task group, and the useful line is buried
under two levels of traceback framing. A rename I can search for. A silently
changed tuple width inside an exception group takes longer to see.

**Workaround** Read the SDK source.

**Suggestion** Either keep `streamablehttp_client` as a deprecated alias for
a release, or have the new one raise a plain `TypeError` naming the change
when unpacked into three. Renaming and changing the shape in the same
release doubles the cost of both.

---

## 5. Writing a completion handler means reading the source

**Task** Offer completions for a `category` argument, so the assistant
suggests a department that exists instead of guessing one.

**Steps** Found `@server.completion()`. Its docstring is "Decorator to
register a completion handler." That is the whole docstring.

**Expected** The handler signature.

**Actual** Nothing in the docstring, nothing I could find in the SDK docs.
I inferred `(ref, argument, context)` and the `Completion(values=, total=,
hasMore=)` return from reading the SDK and the specification side by side.

**Severity** Important. Completion is one of the features that most improves
a voice integration, because a spoken argument is exactly where a client is
most likely to guess wrong, and it is the least documented thing I touched.

**Workaround** Read the source.

**Suggestion** One worked example in the docstring. Four lines would do it.
`Completion` also still uses camelCase `hasMore` while everything around it
is snake_case, which sent me back to entry 3 for a minute.

---

## 6. No way to test against Alexa+ itself

**Task** Confirm the server behaves the same way in front of Alexa+ as it
does in front of a generic MCP client.

**Steps** Looked for a simulator, a sandbox endpoint, or a published
description of how Alexa+ calls an MCP server: how many tools it will
consider, whether `instructions` are honoured, what it does with `cards`,
what happens to a long `speech` string, whether it supports elicitation.

**Expected** Something like the Fire TV simulator, which the same hackathon
provides for the Fire TV track.

**Actual** I built against my own client and the specification. Every
behavioural claim I make about the Alexa+ end is inference.

**Severity** Critical for this track, and the single biggest source of
uncertainty in my submission. The Fire TV track can be demonstrated on a
simulator. The Alexa+ track asks for an integration whose other half cannot
be run.

**Workaround** Wrote the server to be correct against the specification, and
built a client that exercises elicitation both ways so at least the
degradation path is proven rather than assumed.

**Suggestion** Either a hosted echo endpoint that speaks MCP and reports
back what it received, or a short written contract: the client capabilities
Alexa+ advertises, whether it reads `instructions`, and what it does with
structured output that carries both a spoken field and a card list. The
contract alone would remove most of the guesswork, and it is a document
rather than infrastructure.

---

## 7. `MCPServer` advertises no way to subscribe at 2025-11-25

**Task** Let a client watch `shop://cart/{shopper_id}` and be told when the
basket changes, instead of re-reading the resource to find out.

**Steps** Called `ctx.notify_resource_updated(uri)` from the tools that
change the basket, which is what the high-level API offers, then subscribed
from a client and added something.

**Expected** The subscribed client hears about it.

**Actual** Nothing arrives, and the reason is two layers down.
`notify_resource_updated` publishes to the `subscriptions/listen` bus, which
is the 2026-07-28 mechanism. This server negotiates **2025-11-25** - the
version the track requires - where subscriptions are `resources/subscribe`
plus a `resources/updated` notification. `MCPServer` never registers a
`resources/subscribe` handler, and `Server.get_capabilities` derives
`resources.subscribe` at pre-2026 versions from whether that handler exists.
So the server truthfully advertises `subscribe: false`, a well-behaved
client never subscribes, and the only notification API the high-level server
exposes goes somewhere that client is not listening.

**Severity** Important. It is silent in both directions: no error on the
server, and a client that correctly reads the capabilities simply never
asks. A team would reasonably ship this believing subscriptions work,
because the API they called returned cleanly.

**Workaround** Registered `resources/subscribe` and `resources/unsubscribe`
on `server._lowlevel_server` with `add_request_handler`, which also flips the
advertised capability, and sent both notifications: the bus for modern
clients and `session.send_resource_updated` for 2025-11-25 ones.

**Suggestion** Either have `MCPServer` serve `resources/subscribe` while it
still supports a version where that is the mechanism, or make
`notify_resource_updated` fan out to both eras. Failing both, the docstring
should say which era it reaches - it currently mentions the legacy path only
in passing, at the bottom.

---

## 8. The `ServerSession` a handler is given does not survive the request

**Task** Remember which client subscribed to which basket, so an update goes
only to a client that asked for one.

**Steps** Keyed the subscriptions on the `ServerSession` object handed to the
`resources/subscribe` handler - the obvious key, and the one the type
signature invites - then looked it up again from `ctx.session` inside the
tool call.

**Expected** One client, one session object.

**Actual** Different objects. Over Streamable HTTP a fresh `ServerSession` is
built per request, so the session that subscribed is not the session that
later adds to the basket. Every lookup missed and every notification was
dropped, with nothing logged anywhere.

**Severity** Important, and nastier than it sounds because the wrong version
behaves *exactly* like the right one until you check whether the client
actually received anything. It also fails open in the tempting direction: the
easy fix is to stop checking and notify everybody.

**Workaround** Keyed on the transport's own `Mcp-Session-Id` header, which is
stable across requests, reachable from both context shapes, and the actual
identity of the connection. The private `session._connection` turned out to
be stable too, but a private attribute is a worse dependency than a header
the spec defines.

**Suggestion** Give `ServerSession` (or the context) a public, connection-
stable identifier. Every server that holds per-client state - subscriptions,
rate limits, anything - needs one, and right now each has to rediscover that
the session object is not it. A line in the `ServerSession` docstring saying
it is per-request would save the discovery.

---

## What worked well, for balance

- **Elicitation is the right primitive for a confirmation.** Being able to
  ask the user a typed question from inside a tool call, rather than
  returning "please say yes" and hoping the assistant asks, is what let me
  make "no order without a yes" a property of the server instead of a rule
  in the prompt.
- **Structured output with a declared schema** is what makes a voice
  integration possible at all. Being able to say "this field is speech and
  this list is cards" in the schema is the difference between an assistant
  that renders a carousel and one that narrates JSON.
- **Streamable HTTP was the easy part.** The server ran first time and I
  never thought about the transport again, which is the highest compliment
  a transport can get.
- **Resource templates** (`shop://cart/{shopper_id}`) worked exactly as
  written, with no surprises.

## Feature requests

**Evidence-bound fields in an output schema. Priority: important.**
I ask the voice agent for `confirmation_quote`, the customer's own words,
and reject the confirmation when it comes back empty, because a yes nobody
spoke is worse than no yes at all. That check is mine, in my code, and every
other server that needs it will write it again. If a schema could mark a
field as evidence-bound, meaning it must be quoted from what the user
actually said rather than inferred, every tool built on the protocol would
be safer by default.

**A declared speech field. Priority: nice-to-have.**
Voice clients keep reinventing the same convention: one field is meant to be
spoken, the rest is not. A standard annotation would let any assistant know
which string to read aloud without being told in prose, and would stop
servers from having to say "read the speech field exactly" in their
instructions and hope.
