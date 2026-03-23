# kirbus Agent Examples

These examples demonstrate the four agent archetypes described in `docs/ARCHITECTURE.md`.
Each is a standalone `handler.py` you can copy, adapt, and run with:

```bash
kirbus --agent --script <handler.py> --server https://your-server:8443
```

---

## Archetypes

| File | Archetype | Use cases |
|---|---|---|
| `command_response.py` | Command / Response | Home automation, device control, sensor queries |
| `remote_shell.py` | Remote Shell | Raspberry Pi access, remote test runner, server admin |
| `notification_push.py` | Notification / Push | CI build alerts, health monitoring, sensor thresholds |
| `file_bridge.py` | File Bridge | NAS access, shared asset library, log retrieval |

---

## Authentication

Every example checks `sender` before acting. The `sender` parameter is
**cryptographically verified** by the kirbus Ed25519 handshake — it is not
a claim the peer makes, it is proven identity.

Set `allowed_handles` in your agent config to gate connections at the
network level before your handler is ever called:

```toml
# ~/.kirbus/config.toml
[agent]
allowed_handles = ["@yourhandle"]
```

Then check `sender` inside your handler for per-command authorization.

---

## Writing Your Own

The full handler interface:

```python
# Minimal handler — the only required function
def on_message(sender: str, message: str) -> str | None:
    ...
    return reply_or_none

# Optional — called once when a peer connects, with a send() coroutine
# for push-style notifications (see notification_push.py)
async def on_start(send) -> None:
    ...
```

Your handler is a plain Python file. Import whatever you need.
kirbus provides the transport and identity; your handler provides the logic.
