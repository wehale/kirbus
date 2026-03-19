# ezchat Development Phases

A phased roadmap designed to deliver something usable and exciting at the end of every phase. No phase ends with infrastructure alone — each one closes with something you can open, use, and show someone.

---

## Phase 1 — The UI Shell

**Deliverable:** `ezchat --test` opens a fully working retro terminal interface with a built-in echo peer.

This phase is intentionally self-contained. No networking, no crypto, no server. Just the interface — built, themed, and alive.

### What Gets Built

**Curses UI (`ezchat/ui/`)**
- Three-pane layout: presence panel (left), chat window (center/right), input bar (bottom)
- Status bar: handle, connection state, online count
- Chat window: scrollable message history, timestamps, per-sender colour
- Input bar: line editing, history (up/down arrow), command detection (leading `/`)
- Presence panel: user list with `●` / `○` online indicators, arrow-key navigation, `Enter` to connect

**Theme Engine (`ezchat/ui/theme.py`)**
- TOML theme loader
- All five built-in themes: Phosphor Green, Amber Terminal, C64, ANSI BBS, Paper White
- `/theme <name>` switches live without restart
- `~/.ezchat/themes/` directory for user-defined themes

**Echo Bot (`ezchat/test/echobot.py`)**
- `@echobot` responds to every message, every message type
- `--echo-delay <ms>` simulates round-trip latency
- `--echo-script <file>` cycles through scripted responses
- In-process loopback only — for testing over the real network stack, `--echo-server` uses the agent runner with a built-in echo handler (see Phase 10)

**Command Router (`ezchat/commands/router.py`)**
- `/theme <name>` — switch theme
- `/quit` — exit cleanly
- `/who` — toggle presence panel
- Unknown commands shown as error in chat window

**AI Integration (`ezchat/ai/`)**
- `openai-compat` provider targeting local Ollama (`http://localhost:11434/v1`)
- `/ai <prompt>` — query local model, display response in `[AI]` style
- `/ai-share` — echo the AI exchange into the chat (echobot reflects it back)
- `/ai-clear` — discard cached exchange

**Sound Notifications (`ezchat/sounds/`)**
- Built-in retro tones: `terminal_bell`, `bbs_ping`, `modem_chirp`, `key_click`
- Plays on: new message, peer online/offline, file received, AI response ready
- Fully configurable per-event in `config.toml`; any event can point at a custom `.wav`/`.mp3`
- `/sound off` / `/sound on` to toggle mid-session
- `/sound <event> <name>` to change a sound live
- `/sound test` plays all configured sounds in sequence
- `pygame.mixer` for cross-platform playback; lazy-loaded — zero overhead if disabled

**Latency & Benchmarking (`ezchat/bench/`)**
- `timer.py` — lightweight timing primitives available to all modules; zero cost when not benchmarking
- `ping.py` — `/ping` command; measures echo bot round-trip, breaks out enc overhead vs simulated network time
- `suite.py` — `ezchat --bench` runner; crypto section available in Phase 1, later sections added automatically as phases are built
- Phase 1 bench output: AES-256-GCM encrypt+decrypt across message sizes (256B, 1KB, 64KB)

**First-Run Setup (`ezchat/identity.py`)**
- Generate Ed25519 keypair on first launch
- Save to `~/.ezchat/identity.key`
- Prompt for a display handle
- Create `~/.ezchat/config.toml` with defaults

### What You Can Do at the End of Phase 1

```bash
pip install ezchat
ezchat --test
```

- Open a glowing retro chat interface
- Type messages and see `@echobot` respond
- Switch between five retro themes with `/theme`
- Ask your local AI a question with `/ai what is Rust?`
- Share the AI response with `/ai-share` and see how it renders
- See the presence panel with `@echobot` shown as online
- Hear a retro ping when `@echobot` replies
- Change notification sounds with `/sound new_message modem_chirp`
- Mute everything with `/sound off`
- Run `/ping` and see echo bot RTT with encryption overhead broken out
- Run `ezchat --bench` and see the crypto benchmark report

### Dependencies
- `cryptography` (identity key generation only)
- `tomllib` / `tomli`
- `pygame` (sound notifications, optional — disabled if not installed)
- `windows-curses` (Windows only)
- `anthropic` or `openai` (optional, for cloud AI fallback)

---

## Phase 2 — Two People Actually Chatting

**Deliverable:** Alice and Bob can have a real encrypted conversation on the same LAN.

No server required. One side listens, the other connects. Everything is encrypted from the first byte.

### What Gets Built

**Identity & Handshake (`ezchat/crypto/`)**
- X25519 ephemeral key exchange on connect
- Ed25519 identity signatures — each side proves who they are
- AES-256-GCM session key derived from shared secret
- Handshake completes before any chat messages flow

**Network Layer (`ezchat/network/`)**
- Direct TCP listener (`ezchat --listen <port>`)
- Direct TCP connector (`ezchat --connect <host:port>`)
- Length-prefixed JSON envelope framing
- Clean disconnect and reconnect handling

**Encrypted Message Flow**
- All messages encrypted before leaving the process
- All received messages decrypted before display
- Nonce included per-message; auth tags verified

**UI Updates**
- Status bar shows peer handle and `🔒 encrypted` once handshake completes
- Peer handle resolves from their Ed25519 pubkey
- Graceful handling of peer disconnect

### What You Can Do at the End of Phase 2

```bash
# Terminal 1 — Alice
ezchat --listen 9000

# Terminal 2 — Bob (same machine or LAN)
ezchat --connect localhost:9000
```

- Two real terminals exchanging encrypted messages
- Both sides see each other's handles
- Status bar confirms encryption is active
- AI still works locally on each side independently

**Bench additions:** `/ping` now measures real peer RTT; `--bench` gains the `[messages]` section.

### Dependencies
- `cryptography` (full — X25519, Ed25519, AES-GCM)

---

## Phase 3 — Works Anywhere

**Deliverable:** `ezchat-server` deployed on one machine; clients connect from anywhere including through NAT.

### What Gets Built

**`ezchat-server` (`ezchat_server/`)**
- STUN server (RFC 5389, UDP) — endpoint discovery
- TURN relay (UDP/TCP) — fallback for symmetric NAT
- Rendezvous HTTPS API — peer registration and lookup
- Single command: `ezchat-server --config server.toml`
- macOS launchd and Linux systemd service files

**ICE / NAT Traversal (`ezchat/network/ice.py`)**
- `aiortc` ICE negotiation replacing direct TCP
- Connection attempt order: direct → UDP hole punch → TURN relay
- Relay warning shown in UI when TURN is active

**Rendezvous Client (`ezchat/network/rendezvous.py`)**
- Register public endpoint + signed identity on startup
- Look up a peer by handle to get their endpoint
- 60-second TTL keepalive

**Updated Connection Flow**
- `ezchat --server https://chat.company.internal:8443` configures the server
- `ezchat --connect @bob` replaces `--connect host:port`
- Server config saved to `~/.ezchat/config.toml` for future sessions

### What You Can Do at the End of Phase 3

```bash
# Server (company Mac Mini or any machine)
ezchat-server

# Client anywhere — home, office, VPN
ezchat --server https://chat.internal:8443
ezchat --connect @bob
```

- Chat works from home through NAT without port forwarding
- TURN relay kicks in transparently when direct connection fails
- One server command, everything else is automatic

**Bench additions:** `--bench` gains the `[connection]` section — ICE setup timing for direct, hole-punch, and relay paths.

### Dependencies
- `aiortc`
- `aiohttp`

---

## Phase 4 — Find Your Teammates

**Deliverable:** A live user directory. Anyone on the system is discoverable. The presence panel shows who's online right now.

### What Gets Built

**Registry Chain (`ezchat/registry/`)**
- Append-only Merkle block chain: handle + Ed25519 pubkey + display name + signature
- `chain.py` — append, sync, verify, list
- `block.py` — hash/sign/validate per block
- `gossip.py` — broadcast new blocks to server and peers

**Chain Sync API (`ezchat_server/chain_api.py`)**
- Server stores chain as append-only flat file
- Clients sync on startup, receive new blocks as they arrive
- Any peer can verify the entire chain independently

**Presence Panel (live)**
- Full user list from registry chain
- Online indicators refreshed every 30 seconds from rendezvous `/online`
- Online count in status bar: `● 4 online`
- Arrow-key navigation, `Enter` to connect

**`/connect` Command**
- `/connect @alice` — look up Alice's endpoint, establish ICE connection
- Works from the presence panel or the command bar

**Registration Flow**
- First run prompts: `Register a handle? [@yourname]`
- Appends signed block to chain, broadcasts to server
- `/register` command to register or update at any time

**Updated Server Setup**
- `ezchat --server <url>` syncs chain and shows who's registered before first chat

### What You Can Do at the End of Phase 4

```bash
ezchat --server https://chat.internal:8443
```

- See all registered teammates in the presence panel
- See who's online right now with live `●` / `○` indicators
- Arrow to a teammate, press `Enter`, start chatting
- New team member runs one command and appears in everyone's list

**Bench additions:** `--bench` gains the `[chain]` section — block append time, gossip latency, and full sync time.

### Dependencies
- No new external dependencies — registry chain is pure Python

---

## Phase 5 — Reliable Delivery

**Deliverable:** Messages get through even when a peer is offline. Sender always knows the delivery state of every message.

### What Gets Built

**Client-Side Queue (`ezchat/delivery/queue.py`)**
- Undelivered messages written to `~/.ezchat/queue/@handle/`
- Presence watch registered with rendezvous: "notify me when @bob appears"
- Queue flushed automatically when peer comes online
- Queue survives client restarts

**Delivery Status (`ezchat/delivery/status.py`)**
- Per-message status indicator in chat window
- `·` pending — queued, peer not yet seen
- `⇡` buffered — in server buffer (if enabled)
- `✓` delivered — confirmed received
- `✗` expired — TTL elapsed without delivery (server buffer only)

**Server-Side Buffer (`ezchat_server/buffer.py`) — optional**
- Enabled by IT admin in `server.toml`: `buffer.enabled = true`
- Accepts encrypted ciphertext only — server cannot read content
- Sealed sender — sender identity hidden from server inside ciphertext
- Configurable TTL (default 7 days) and max message size
- Client auto-detects whether server has buffering enabled

**IT Admin Config**
```toml
# server.toml
[buffer]
enabled  = true
ttl_days = 7
max_kb   = 512
```

### What You Can Do at the End of Phase 5

- Send a message to an offline teammate — it queues silently
- Teammate comes online — message delivers automatically, status flips to `✓`
- With buffer enabled: teammate receives messages even if you closed your client first
- Every message has a visible delivery state at all times

---

## Phase 6 — AI in Real Conversations

**Deliverable:** `/ai` and `/ai-share` work in live peer-to-peer chat sessions.

Phase 1 built AI against the echo bot. This phase wires it into real conversations.

### What Gets Built

**AI in Live Sessions**
- `/ai <prompt>` — queries local Ollama (or configured cloud provider), response shown locally only
- `/ai-share` — sends last AI exchange to peer as `[AI-SHARE]` block, rendered distinctly
- `/ai-clear` — discard cached exchange without sharing

**Provider Abstraction (`ezchat/ai/`)**
- `AnthropicProvider` — Anthropic API
- `OpenAIProvider` — OpenAI API
- `OpenAICompatProvider` — any OpenAI-compatible endpoint (Ollama, LM Studio, llama.cpp)

**AI Share Rendering**
```
[AI-SHARE] @alice asked: what are the SOLID principles?
[AI-SHARE] Single responsibility, Open-closed, Liskov...
```

**Config**
```toml
[ai]
provider = "openai-compat"
api_key  = "none"
model    = "llama3.2"
base_url = "http://localhost:11434/v1"
```

### What You Can Do at the End of Phase 6

- Ask your local model something mid-conversation without the peer seeing it
- Decide to share the response with `/ai-share`
- Peer sees the full exchange formatted clearly in their chat window
- Everything stays on your machines — no prompts leave the network

---

## Phase 7 — File Transfer

**Deliverable:** `/send <file>` transfers any file directly to a peer, encrypted, with progress shown in the chat window.

### What Gets Built

**File Sender (`ezchat/files/sender.py`)**
- Read file, compute SHA-256
- Send `file_offer` envelope to peer
- On acceptance: chunk file (64 KB default), encrypt each chunk with session key
- Stream chunks, track progress

**File Receiver (`ezchat/files/receiver.py`)**
- Prompt user on incoming `file_offer`
- Reassemble and decrypt chunks in order
- Verify final SHA-256 hash
- Write to `~/Downloads/ezchat/`
- Show completion with full save path

**Progress in Chat Window**
```
[FILE]  @alice → report.pdf  2.3 MB          [Y]es / [N]o
[FILE]  report.pdf  [████████████░░░░]  75%  1.7 / 2.3 MB
[FILE]  ✓ report.pdf  2.3 MB  → ~/Downloads/ezchat/
```

**TURN Relay Warning**
- If connection is relayed rather than direct, warn before large transfer begins

**Commands**
- `/send <path>` — offer a file
- `/accept` — accept incoming offer (or press `Y`)
- `/decline` — decline (or press `N`)
- `/transfers` — show active and recent transfers

**Config**
```toml
[files]
download_dir = "~/Downloads/ezchat"
max_size_mb  = 500
auto_accept  = false
chunk_kb     = 64
```

### What You Can Do at the End of Phase 7

- `/send design_mockup.png` — teammate accepts, file arrives in their Downloads
- They open it from VSCode Explorer or Finder without leaving their workflow
- Transfer is encrypted end-to-end; server never sees the file

---

## Phase 8 — Production Hardening

**Deliverable:** Ready for a real team to depend on daily. Packaged, documented, and auditable.

### What Gets Built

**Protocol Specification (`docs/PROTOCOL.md`)**
- Wire format, handshake sequence, chain block structure
- Language-agnostic — prerequisite for future mobile client
- Covers all envelope types including file transfer chunks

**Packaging & Deployment**
- `Dockerfile` and `docker-compose.yml` for `ezchat-server`
- macOS `.pkg` installer for the client
- Proper `pyproject.toml` with pinned dependencies and entry points

**TLS for `ezchat-server`**
- Let's Encrypt / ACME support for public deployments
- Self-signed cert generation for internal deployments (already in Phase 3, hardened here)

**Security Review**
- Audit X25519 + AES-GCM implementation against spec
- Verify sealed sender implementation
- Review chain block signature verification for edge cases
- Fuzz the message framing parser

**Operational Docs**
- `docs/DEPLOYMENT.md` — full IT admin setup guide
- `docs/SELF_HOSTING.md` — running your own server instance
- `CONTRIBUTING.md` — for open source contributors

### What You Can Do at the End of Phase 8

- Hand `docs/DEPLOYMENT.md` to an IT admin and walk away
- Run `docker-compose up` to start the full server stack
- Point to `docs/PROTOCOL.md` when scoping the mobile client

---

## Phase Dependency Map

```
Phase 1 (UI Shell)
    │
    ▼
Phase 2 (LAN Chat) ──────────────────────────────────┐
    │                                                 │
    ▼                                                 │
Phase 3 (NAT / ezchat-server)                         │
    │                                                 │
    ▼                                                 │
Phase 4 (Registry Chain + Presence)                   │
    │                                                 │
    ├──► Phase 5 (Offline Delivery)                   │
    │                                                 │
    ├──► Phase 6 (AI in Live Chat) ◄──────────────────┘
    │
    ├──► Phase 7 (File Transfer)
    │
    └──► Phase 8 (Production Hardening)
         │
         ├──► Phase 9 (Games)
         │
         ├──► Phase 10 (Headless Agents)
         │
         └──► Future: Mobile Client (requires PROTOCOL.md)
```

Phases 5, 6, and 7 are independent once Phase 4 is complete and can be built in parallel or reordered based on what the team needs most. Phase 9 is independent of everything after Phase 2 — it only needs a working P2P connection.

---

## Phase 9 — Games

**Deliverable:** `/game chess` challenges your peer to a game. Every game renders in your active theme — phosphor green chess, amber battleship, C64 pong.

This phase is purely additive — no existing features change. Games are a new module that plugs into the P2P connection and the theme engine.

### What Gets Built

**Game Framework (`ezchat/games/base.py`)**
- `Game` abstract base class: `render()`, `handle_input()`, `handle_peer()`, `on_start()`, `on_end()`
- Game loop: takes over the full terminal, suspends chat window display
- Background message buffering — messages received during a game wait silently and appear on return
- `ESC` / `/quit-game` concedes and returns to chat
- End-of-game summary line in chat history: `[GAME] Chess vs @bob — @bob won (14 moves, 8 minutes)`

**Theme Integration**
- Every game pulls colours from the active theme at render time
- No per-game colour config — theme `foreground`, `accent`, `background`, and `error_fg` map to game elements automatically
- Switching theme mid-game re-renders immediately

**Turn-Based Games**
- **Tic-tac-toe** (`tictactoe.py`) — simplest game; exercises the framework end-to-end
- **Connect Four** (`connect_four.py`) — 7×6 grid; each player's pieces in distinct theme colours
- **Hangman** (`hangman.py`) — word guessing; gallows in ASCII; letter bank in theme foreground
- **Battleship** (`battleship.py`) — dual 10×10 grids; ships in accent colour, hits in error colour
- **Chess** (`chess.py`) — full rules; Unicode pieces; light/dark squares from theme palette

**Real-Time Games**
- **Pong** (`pong.py`) — paddles as `█` blocks in theme accent; ball as `●`; score in status bar; state updates at 30 fps over the P2P channel

**Network Events**
- `game_invite` — challenge a peer, includes game name
- `game_event` — a move or state update, encrypted with session key
- `game_over` — result and winner

**Sound Integration**
- Move confirmation: `key_click`
- Win: `bbs_ping`
- Loss: silent by default, configurable
- All wired into the existing sound system — no new audio infrastructure

**Commands**
- `/game <name>` — challenge current peer
- `/game list` — show available games
- `/quit-game` — concede and return to chat

### What You Can Do at the End of Phase 9

```
/game chess
```

- Peer sees: `[GAME] @alice is challenging you to Chess  [Y]es / [N]o`
- Full-screen chess board renders in your current theme colours
- Moves exchange over the encrypted P2P connection
- `ESC` drops you back into chat — messages sent during the game are waiting
- Game summary appears in chat history

### Dependencies
- No new external dependencies — all rendering via `curses`, game logic pure Python

---

## Phase 10 — Headless Agents

**Deliverable:** `ezchat --agent --script handler.py` runs a headless ezchat client that passes every received message to a user-supplied Python script and optionally sends a reply. Any device or service can join the ezchat network as a first-class participant.

ezchat does not define a command protocol for agents. The handler — and the people or systems connecting to it — define whatever message format makes sense for their integration. ezchat's role is encrypted delivery and identity, nothing more.

This phase requires no protocol changes. It is purely additive: a new execution mode with no UI, and `type: "agent"` added to registry chain blocks.

### What Gets Built

**Agent Runner (`ezchat/agent/runner.py`)**
- Full ezchat network and crypto stack, no curses UI
- On message received: call `handler.on_message(sender, text)`
- If handler returns a string: send it back as a reply
- Logs to stdout or file; no terminal interaction required
- Runs as a long-lived background service via launchd or systemd

**Handler Loader (`ezchat/agent/loader.py`)**
- Loads `handler.py` from disk on startup
- Hot-reloads when the file changes — update the handler without restarting the agent

**Agent Registration**
- Registry chain block gains `type: "agent"` and optional `description` field
- Presence panel renders agents with `⚙` instead of `●`/`○`
- `/connect @agent-handle` works identically to connecting to a person

**`--agent` CLI flag**
- `ezchat --agent --script handler.py`
- `ezchat --agent --script handler.py --server https://chat.internal:8443`

**Example handlers (`examples/agents/`)**
- `command_response.py` — command / response archetype template
- `remote_shell.py` — remote shell (Raspberry Pi, headless server access)
- `notification_push.py` — background watch loop with push messages
- `file_bridge.py` — shared file server over the chat channel

### Authentication

The `sender` passed to the handler is cryptographically verified by the Ed25519 handshake — not a claim, proven identity. The handler can safely use it for authorization decisions without any additional auth mechanism.

Two layers ship out of the box:

**Config-level allowlist** — rejects unknown handles before the handler is ever called:
```toml
[agent]
allowed_handles = ["@alice", "@bob"]   # empty = nobody can connect
```

**Handler-level authorization** — fine-grained per-command control:
```python
ADMINS  = {"@alice"}
TRUSTED = {"@alice", "@bob"}

def on_message(sender: str, message: str) -> str | None:
    if sender not in TRUSTED:
        return None  # reveal nothing to unknown senders
    if message == "unlock door" and sender not in ADMINS:
        return "Not authorised."
    ...
```

### Handler Interface

```python
# handler.py — define whatever protocol your integration requires.
# ezchat delivers the string and a verified sender identity; you decide what to do with both.

def on_message(sender: str, message: str) -> str | None:
    # sender is cryptographically verified — safe to use for authorization
    ...
    return response_or_none
```

### What You Can Do at the End of Phase 10

```bash
# On any always-on machine
pip install ezchat
ezchat --agent --script /path/to/handler.py --server https://chat.internal:8443
```

- Any Python-capable device joins the ezchat network as a named, encrypted participant
- The agent appears in the presence panel alongside teammates with `⚙`
- Users connect to it like any other peer and exchange whatever strings their integration defines
- E2E encrypted throughout — the server never sees the content
- No ezchat protocol changes required

### Dependencies
- No new dependencies in ezchat — the handler supplies its own
