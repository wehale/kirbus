# ezchat Architecture

A peer-to-peer, end-to-end encrypted terminal chat platform with AI integration, a retro curses UI, a built-in user registry chain, and optional tamper-evident message logging.

---

## Table of Contents

1. [Overview](#overview)
2. [Goals & Non-Goals](#goals--non-goals)
3. [System Components](#system-components)
4. [Network Layer](#network-layer)
5. [NAT Traversal & Rendezvous](#nat-traversal--rendezvous)
6. [Encryption & Security](#encryption--security)
7. [Terminal UI](#terminal-ui)
8. [AI Integration](#ai-integration)
9. [Registry Chain](#registry-chain)
10. [ezchat-server](#ezchat-server)
11. [Offline Message Delivery](#offline-message-delivery)
12. [File Transfer](#file-transfer)
13. [Sound Notifications](#sound-notifications)
14. [Games](#games)
15. [Headless Agents](#headless-agents)
16. [Private / Self-Hosted Deployment](#private--self-hosted-deployment)
17. [Latency Testing & Benchmarking](#latency-testing--benchmarking)
18. [Test Mode](#test-mode)
19. [Data Flow](#data-flow)
20. [Module Structure](#module-structure)
21. [Open Questions](#open-questions)

---

## Overview

ezchat is a Python terminal application that enables direct, encrypted peer-to-peer chat between two users without a central server. It renders a retro-style curses interface that users can skin with classic terminal aesthetics. Users may optionally configure an LLM API key to interact with AI inline during chat, and share those AI exchanges with their peer. A built-in Merkle registry chain provides a decentralized, gas-free user directory — no external blockchain node or wallet required. An optional tamper-evident message log extends this chain for users who want auditability.

---

## Goals & Non-Goals

### Goals

- Direct P2P connections — no central server required for messaging; a stateless rendezvous server assists with NAT traversal only
- End-to-end encryption on all messages
- Terminal UI built with `curses`, skinnable with multiple retro themes
- `/ai <prompt>` — send a prompt to a configured LLM and display the response privately
- `/ai-share` — share the last AI prompt and response into the chat with the peer
- Built-in Merkle user registry — discover all users on the system; no external blockchain, no gas, no wallet required
- User registry stores identity only — no chat state, no message history, no online status
- Optional tamper-evident message log anchored to the registry chain
- Single-command setup: `pip install ezchat && ezchat` — everything initializes automatically
- Provably stateless rendezvous server — no message content, no persistent storage, open source so anyone can self-host

### Non-Goals

- Group chat (multi-party) — out of scope for v1
- Mobile or GUI clients
- Inline file rendering in the terminal — files are saved to disk and opened in the user's file browser
- Central server that stores messages or user state

---

## System Components

```
┌─────────────────────────────────────────────────────────────┐
│                        ezchat process                       │
│                                                             │
│  ┌──────────┐   ┌──────────────┐   ┌─────────────────────┐ │
│  │  Curses  │   │   Message    │   │    AI Interface     │ │
│  │   UI     │◄──│   Router     │──►│  (LLM API client)   │ │
│  │  Layer   │   │              │   └─────────────────────┘ │
│  └────┬─────┘   └──────┬───────┘                           │
│       │                │                                    │
│  ┌────▼─────┐   ┌──────▼───────┐   ┌─────────────────────┐ │
│  │  Theme   │   │  Encryption  │   │  Blockchain Client  │ │
│  │  Engine  │   │  Layer (E2E) │   │  (optional)         │ │
│  └──────────┘   └──────┬───────┘   └─────────────────────┘ │
│                        │                                    │
│                 ┌──────▼───────┐                            │
│                 │  P2P Network │                            │
│                 │  Layer       │                            │
│                 └──────────────┘                            │
└─────────────────────────────────────────────────────────────┘
```

### Component Summary

| Component | Responsibility |
|---|---|
| **Curses UI Layer** | Render chat window, input bar, status bar; dispatch commands |
| **Theme Engine** | Load and apply retro skin definitions |
| **Message Router** | Parse commands (`/ai`, `/ai-share`, `/quit`), route to correct handler |
| **Encryption Layer** | Key exchange, encrypt/decrypt all messages before network I/O |
| **P2P Network Layer** | Establish and maintain direct connection to peer via ICE/STUN/TURN |
| **Rendezvous Client** | Register with and query the stateless rendezvous server for peer discovery |
| **AI Interface** | Call configured LLM API, cache last prompt/response for `/ai-share` |
| **Registry Chain** | Built-in Merkle chain for user discovery; gossiped between peers and rendezvous server |
| **Chain Client** | Read/write the registry chain; optionally anchor message hashes for tamper-evident logs |

---

## Network Layer

### Transport

- **Protocol:** UDP (primary, via ICE/hole-punching) with TCP fallback through TURN relay
- **Library:** `aiortc` — handles ICE, STUN, and TURN negotiation; `asyncio` for all async I/O
- **Connection strategy:** ICE negotiation selects the best available path (see NAT Traversal section)

### Connection Lifecycle

```
Alice                    Rendezvous Server              Bob
  │                            │                          │
  │── STUN request ───────────►│  (learns public IP:port) │
  │◄── public endpoint ────────│                          │
  │                            │                          │
  │── register(@alice,         │                          │
  │     endpoint, signed) ────►│  [in-memory, 60s TTL]   │
  │                            │                          │
  │                            │◄─ lookup(@alice) ────────│
  │                            │── endpoint ─────────────►│
  │                            │  [server forgets]        │
  │                            │                          │
  │◄══ ICE/UDP hole punch ════════════════════════════════│
  │══ ICE/UDP hole punch ═════════════════════════════════►│
  │                            │                          │
  │◄══════════ Direct P2P connection established ════════►│
  │                            │                          │
  │◄─── [Handshake: pubkey] ─────────────────────────────│  ← E2E key exchange
  │──── [Handshake: pubkey] ────────────────────────────►│
  │                            │                          │
  │◄═══════════════ Encrypted messages ══════════════════►│
```

### Message Framing

Each message over the wire is a length-prefixed JSON envelope:

```
[4-byte big-endian length][JSON payload (encrypted)]
```

Envelope fields:

```json
{
  "v": 1,
  "type": "msg" | "ai_share" | "sys",
  "ts": "<ISO-8601 timestamp>",
  "body": "<base64-encoded ciphertext>"
}
```

---

## NAT Traversal & Rendezvous

Most users are behind NAT (home routers, corporate firewalls, mobile carriers). A pure "just connect" P2P approach fails in these environments. ezchat solves this with a layered strategy and a deliberately stateless rendezvous server.

### Connection Attempt Order

```
1. Direct connection (same LAN, known public IP, or manual port forward)
        ↓ fails
2. UDP hole punching via STUN + ICE  [works for ~75% of NATs]
        ↓ fails (symmetric NAT)
3. TURN relay fallback               [always works; still E2E encrypted]
```

### The Rendezvous Server

The rendezvous server is a small, open-source Python service with a deliberately minimal and auditable design.

**What it stores:**
- A short-lived in-memory mapping of `handle → (public_ip, public_port, pubkey, signature)`
- TTL: 60 seconds — entries expire automatically and are never written to disk

**What it never stores:**
- Message content (it never sees any)
- Session associations (it does not know that Alice looked up Bob)
- Persistent state of any kind — a server restart wipes everything

**How registrations are authenticated:**

Each registration is signed with the user's Ed25519 identity key. The server verifies the signature before accepting the registration — it cannot be spoofed by a third party claiming to be `@alice` without Alice's private key.

```
Registration payload (sent over HTTPS):
{
  "handle":    "@alice",
  "pubkey":    "<base58 Ed25519 pubkey>",
  "endpoint":  "203.0.113.5:41000",
  "ts":        "2026-03-18T10:42:00Z",
  "sig":       "<Ed25519 signature over handle+pubkey+endpoint+ts>"
}
```

**Provable statelessness:**
- No database dependency
- No log files
- Open source — anyone can read the code and self-host
- The server operator learns: "at time T, IP X claimed to be @alice" — and forgets after 60s
- The server never learns who Alice talked to

### STUN: Discovering Your Public Endpoint

A STUN server (RFC 5389) is inherently stateless — it receives a UDP packet and reflects back the client's public IP and port as seen from the internet. It stores nothing. ezchat contacts a STUN server on startup to discover its own public endpoint before registering with the rendezvous server.

Public STUN servers (e.g., Google's `stun.l.google.com:19302`) can be used, or the ezchat rendezvous server can double as the STUN server.

### UDP Hole Punching

Once both peers have each other's public endpoints (via the rendezvous server), they simultaneously send UDP packets to each other. Each NAT sees outbound traffic to the peer's address and opens a pinhole — allowing the peer's packets to flow back through.

`aiortc` implements ICE (RFC 8445), which automates this negotiation including candidate gathering, connectivity checks, and path selection.

### TURN Relay Fallback

Symmetric NAT assigns a different public port for each destination, making hole punching unreliable. When ICE fails to establish a direct path, it falls back to a TURN relay server.

**Critically:** TURN only relays encrypted bytes. The relay server sees:
- Source and destination IP:port
- Opaque ciphertext (AES-256-GCM)

It does **not** see message content, user identities, or handles. The E2E encryption guarantee is preserved even through a relay.

### Module: `network/rendezvous.py`

```python
class RendezvousClient:
    async def register(self, handle: str, endpoint: str) -> None: ...
    async def lookup(self, handle: str) -> str | None: ...  # returns "ip:port" or None
```

### Rendezvous Server Configuration

```toml
[rendezvous]
url = "https://rendezvous.ezchat.example"  # default public instance
ttl = 60                                    # seconds
```

Users who want full sovereignty can self-host the open-source rendezvous server and point their config at it.

---

## Encryption & Security

### Key Exchange

- **Algorithm:** X25519 Diffie-Hellman (via `cryptography` library)
- Each session generates a fresh ephemeral X25519 keypair
- Public keys are exchanged in plaintext during the handshake
- A shared secret is derived and used to produce a symmetric session key

### Symmetric Encryption

- **Algorithm:** AES-256-GCM
- A unique 96-bit nonce is generated per message
- The nonce is prepended to the ciphertext and included in the envelope
- Authentication tags prevent tampering

### Identity (persistent keys)

- Users have a long-term Ed25519 keypair stored in `~/.ezchat/identity.key`
- The public key serves as the user's address/identity (`@<base58-pubkey>`)
- During handshake, each side signs the ephemeral key with their identity key so the peer can verify they're talking to the expected user

### Forward Secrecy

- Ephemeral session keys mean past sessions cannot be decrypted if a long-term key is later compromised
- Session keys are never written to disk

---

## Terminal UI

### Library

`curses` (stdlib) with `curses.textpad` for input. No external TUI dependency required. `windows-curses` used on Windows if needed.

### Layout

```
┌──────────────────────────────────────────────────────┐
│ ezchat  ◄──── title / status bar (peer, encryption)  │
├──────────────────────────────────────────────────────┤
│                                                      │
│  [10:42] @alice: hello                               │
│  [10:42] @bob:   hey there                           │
│  [10:43] @alice: /ai what is the weather like?       │
│  [AI]    It's sunny and 72°F in your area.           │
│                                                      │
│                                                      │
├──────────────────────────────────────────────────────┤
│ > _                          ◄──── input bar         │
└──────────────────────────────────────────────────────┘
```

### Skinning / Themes

Themes are defined as TOML files in `~/.ezchat/themes/` (built-in themes ship in `ezchat/themes/`).

A theme file defines:

```toml
[meta]
name = "Phosphor Green"
description = "Classic green-on-black CRT terminal"

[colors]
background  = "black"
foreground  = "green"
accent      = "bright_green"
input_bg    = "black"
input_fg    = "green"
status_bg   = "green"
status_fg   = "black"
ai_fg       = "cyan"
error_fg    = "red"
timestamp_fg = "dark_green"

[border]
style = "single"      # single | double | rounded | ascii | none
title_align = "left"  # left | center | right
```

#### Built-in Themes

| Theme Name | Aesthetic |
|---|---|
| **Phosphor Green** | Classic green-on-black CRT |
| **Amber Terminal** | Amber/orange on black, IBM 3179 style |
| **C64** | Commodore 64 blue/light blue |
| **ANSI BBS** | Bold ANSI colors, BBS-era feel |
| **Paper White** | White background, dark text, teletype feel |

Users switch themes with `/theme <name>` at runtime or set a default in `~/.ezchat/config.toml`.

---

## AI Integration

### Configuration

Users store their LLM configuration in `~/.ezchat/config.toml`.

**Cloud provider (default for individual users):**

```toml
[ai]
provider = "anthropic"   # anthropic | openai | openai-compat
api_key  = "sk-..."
model    = "claude-sonnet-4-6"
base_url = ""
```

**Local model (recommended for private deployments):**

Each user runs a local inference server — [Ollama](https://ollama.com) is the simplest option and works well on Apple Silicon (Mac Mini, MacBook Pro). The `openai-compat` provider targets any OpenAI-compatible local endpoint, so LM Studio, llama.cpp server, and others work equally well.

```toml
[ai]
provider = "openai-compat"
api_key  = "none"                         # local servers don't require a key
model    = "llama3.2"                     # or any model pulled via ollama
base_url = "http://localhost:11434/v1"    # Ollama default
```

With this configuration, AI prompts never leave the user's machine. No API key is needed, no external service is contacted, and the model runs entirely on local hardware.

### Commands

| Command | Behavior |
|---|---|
| `/ai <prompt>` | Send prompt to LLM. Display response locally only (not sent to peer). Caches prompt + response. |
| `/ai-share` | Send the last cached AI prompt and response as a special `ai_share` message to the peer. Both sides see it formatted distinctly. |
| `/ai-clear` | Clear the cached prompt/response without sharing. |

### AI Message Display

AI responses are rendered in a distinct color (per theme, `ai_fg`) and prefixed with `[AI]` to visually separate them from chat messages.

Shared AI exchanges are rendered for the peer as:

```
[AI-SHARE] @alice asked: what is the capital of France?
[AI-SHARE] Response: The capital of France is Paris.
```

### Provider Abstraction

An `AIProvider` abstract base class allows swapping providers:

```python
class AIProvider(ABC):
    async def complete(self, prompt: str) -> str: ...
```

Concrete implementations: `AnthropicProvider`, `OpenAIProvider`, `OpenAICompatProvider`.

---

## Registry Chain

The registry chain is ezchat's built-in blockchain: a purpose-built, append-only Merkle chain that serves as the system-wide user directory. It requires no external node, no gas, no wallet beyond the Ed25519 identity key every user already has.

### What It Stores

User identity records only. No chat state, no message content, no session history.

```
┌─────────────────────────────────────────────────┐
│                   Block N                        │
│                                                  │
│  prev_hash:    SHA-256(Block N-1)                │
│  handle:       "@alice"                          │
│  pubkey:       <base58 Ed25519 pubkey>           │
│  display_name: "Alice"           (optional)      │
│  bio:          "..."             (optional)      │
│  ts:           "2026-03-18T..."                  │
│  sig:          Ed25519 signature over all fields │
│  block_hash:   SHA-256(this block's fields)      │
└─────────────────────────────────────────────────┘
```

The `sig` field proves the registrant controls the private key corresponding to `pubkey`. The `prev_hash` field chains blocks together — altering any block invalidates all subsequent hashes, making tampering detectable by any peer.

### Chain Structure

```
Genesis (empty, well-known hash)
     │
     ▼
Block 1: @alice registered
     │
     ▼
Block 2: @bob registered
     │
     ▼
Block 3: @alice updated display_name
     │
     ▼
    ...
```

Updates (e.g. changing a display name) append a new block rather than mutating an existing one. The chain is an immutable log; the latest block for a given handle is the canonical record.

### Gossip & Sync

The chain is gossiped between all participants — no single node owns it.

```
New user registers
  → appends block to local chain
    → broadcasts block to rendezvous server
      → rendezvous server gossips to connected peers
        → each peer validates (hash + signature) and appends
```

On startup, a client syncs the full chain from the rendezvous server (or any known peer). The rendezvous server holds the chain in memory and persists it to a flat append-only file — the only persistent state it keeps.

Any peer can verify the entire chain independently: check every `prev_hash` linkage and every `sig`. A single invalid block is rejected; the rest of the chain remains valid.

### Online/Offline Status

Online presence is derived by cross-referencing the two systems:

- **Registry chain** → who exists (persistent, handle + pubkey)
- **Rendezvous server** → who is currently reachable (ephemeral, 60s TTL)

The `/who` command displays the full user list from the chain, with a live indicator for handles that have an active rendezvous registration.

### Registration: Opt-In

Adding yourself to the registry is explicit (`/register` command or a flag on first run). A user who prefers not to appear in the directory simply doesn't register — they can still connect directly with a peer who knows their handle or public endpoint.

### Optional: Tamper-Evident Message Log

Users who want auditability can optionally anchor message hashes into the chain. After each message exchange, `SHA-256(ts + sender_pubkey + ciphertext)` is appended as a lightweight `msg_anchor` block. This creates a verifiable transcript without storing message content anywhere in the chain.

This feature is off by default and must be agreed upon by both peers before a session begins.

### Chain Abstraction

```python
class RegistryChain:
    async def append(self, record: UserRecord | MsgAnchor) -> Block: ...
    async def sync(self, peer: str) -> int: ...           # returns blocks synced
    async def get_user(self, handle: str) -> UserRecord | None: ...
    async def list_users(self) -> list[UserRecord]: ...
    async def verify(self) -> bool: ...                   # full chain integrity check
```

### First-Run Setup

On the very first run, ezchat:

1. Generates an Ed25519 identity keypair and saves it to `~/.ezchat/identity.key`
2. Syncs the registry chain from the configured rendezvous server
3. Prompts the user to optionally register a handle
4. If registering: appends a signed block, broadcasts it to the rendezvous server

All of this happens before the chat UI opens. Total time: under a second on a normal connection.

### Configuration

```toml
[registry]
rendezvous_url = "https://rendezvous.ezchat.example"
auto_register  = false    # prompt on first run; set true to skip the prompt
msg_anchoring  = false    # opt-in tamper-evident message log
```

---

## ezchat-server

`ezchat-server` is the single command that runs all server-side infrastructure. It is a small, self-contained Python process that ships in the same package as the client — no separate install required.

### What It Runs

```
ezchat-server
  ├── STUN server        (UDP, RFC 5389)   — endpoint discovery
  ├── TURN relay         (UDP/TCP)         — fallback relay for symmetric NAT
  ├── Rendezvous API     (HTTPS)           — peer registration and lookup
  └── Chain sync API     (HTTPS)           — registry chain gossip endpoint
```

All four services run as `asyncio` tasks within a single process. There is no database process, no message broker, no external dependency beyond Python and the packages already required by the client.

### What the Server Stores

| Data | Storage | Lifetime |
|---|---|---|
| Peer registrations (handle → endpoint) | In-memory only | 60s TTL, lost on restart |
| Registry chain (handle → pubkey records) | Append-only flat file | Permanent (identity log) |
| TURN relay sessions | In-memory only | Duration of relay session |
| Message content | Never stored | — |

The only file the server ever writes is the registry chain log. Everything else is ephemeral.

### Starting the Server

```bash
# Install (once)
pip install ezchat

# Run the server
ezchat-server

# With custom config
ezchat-server --config /etc/ezchat/server.toml

# Or via Docker
docker run -p 3478:3478/udp -p 8443:8443 ezchat/server
```

On first start, `ezchat-server` generates a self-signed TLS certificate for the HTTPS APIs if none is provided. For production internal use, operators can supply their own cert.

### Server Configuration

```toml
# /etc/ezchat/server.toml  (or ~/.ezchat/server.toml)

[server]
host        = "0.0.0.0"
stun_port   = 3478       # standard STUN port (UDP)
turn_port   = 3478       # TURN shares the STUN port
api_port    = 8443       # HTTPS rendezvous + chain sync API
tls_cert    = ""         # path to cert file; auto-generated if empty
tls_key     = ""         # path to key file; auto-generated if empty
log_level   = "warn"     # debug | info | warn | error

[rendezvous]
ttl         = 60         # seconds before a peer registration expires

[turn]
realm       = "ezchat"
credentials = []         # list of {username, password} for TURN auth
                         # leave empty to allow unauthenticated relay (LAN-only)

[chain]
data_dir    = "~/.ezchat/server"   # where the chain flat file is written
```

### Server Resource Footprint

`ezchat-server` is intentionally lightweight. On a Mac Mini M2 or comparable machine it uses:
- ~30 MB RAM at idle
- Negligible CPU (event-driven, no polling)
- Disk: only the registry chain file, which grows by one small block per user registration

It is suitable to run as a background service alongside other workloads, or dedicated on any always-on machine on the network (a Mac Mini, a Raspberry Pi, a small cloud VM).

### Running as a Background Service

**macOS (launchd):**

```xml
<!-- ~/Library/LaunchAgents/com.ezchat.server.plist -->
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ezchat.server</string>
  <key>ProgramArguments</key>
  <array><string>/usr/local/bin/ezchat-server</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.ezchat.server.plist
```

**Linux (systemd):**

```ini
# /etc/systemd/system/ezchat-server.service
[Unit]
Description=ezchat server
After=network.target

[Service]
ExecStart=/usr/local/bin/ezchat-server
Restart=always
User=ezchat

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now ezchat-server
```

---

## Offline Message Delivery

When a recipient is offline, ezchat provides two complementary delivery mechanisms. Both are available simultaneously. The IT admin decides which are enabled for their deployment.

### Mode 1: Client-Side Queue (always on)

The sender's client stores undelivered messages locally and delivers them directly when both peers are online at the same time. No message content ever touches the server.

```
Alice sends to Bob (offline)
  → direct delivery fails
    → message written to ~/.ezchat/queue/@bob/
      → client registers a presence watch with the rendezvous server

Bob comes online
  → rendezvous server fires a one-time notify to Alice's client
    → Alice's client connects directly to Bob
      → queue flushed over P2P connection
        → messages deleted from queue on confirmation
```

**Presence watch** — rather than polling, Alice's client sends a lightweight subscription to the rendezvous server: `"notify me when @bob registers"`. The server holds this in memory (same 60s TTL mechanism as all rendezvous state). When Bob registers, the server pings Alice's endpoint once and discards the subscription. The server never sees the queued messages.

The local queue survives client restarts. If Alice closes her client before Bob comes online, the queue persists in `~/.ezchat/queue/`. When Alice's client next opens and Bob is online, delivery happens automatically.

**The one limitation:** if Alice's client is closed and Bob is online, delivery waits until Alice reopens her client. For a work context where people keep clients open during business hours, this is rarely a problem in practice.

### Mode 2: Server-Side Buffer (opt-in, IT admin)

When enabled by the IT admin, the server accepts encrypted messages for offline recipients and holds them until delivery. The server stores only ciphertext it cannot read.

```
Alice sends to Bob (offline, buffer enabled)
  → direct delivery fails, client queue written as normal
    → encrypted message also handed to server buffer
      → server stores {recipient: "@bob", ciphertext: "...", ttl: "7d"}
        → server cannot decrypt — Alice's key never leaves her machine

Bob comes online
  → server: "you have 2 buffered messages"
    → Bob fetches ciphertext from server
      → decrypts locally
        → server deletes buffered messages on delivery confirmation
```

**Sealed sender** — Alice's identity is encrypted inside the message body before it reaches the server. The server sees only the recipient handle and opaque ciphertext. It does not know who sent the message.

**With both modes active**, messages are written to Alice's local queue *and* the server buffer. Whichever path delivers first wins. This means Bob gets messages even if Alice is offline, and Alice's queue cleans up once Bob confirms receipt.

### Delivery Priority

```
1. Direct P2P                    (recipient online, both clients open)
        ↓ fails
2. Client queue + presence watch (recipient offline, sender client open)
        ↓ sender client also offline
3. Server buffer                 (if enabled — recipient fetches on next login)
```

### What Each Mode Reveals to the Server

| | Client Queue Only | Server Buffer Enabled |
|---|---|---|
| Message content | Never | Never (ciphertext only) |
| That Alice sent *something* to Bob | No | Yes (metadata) |
| When Bob came online | No | Yes |
| Sender identity | N/A | Hidden (sealed sender) |
| Message size | No | Yes (approximate) |

For deployments where even metadata exposure is unacceptable, the IT admin leaves the buffer disabled and accepts the "both clients must overlap" constraint. For deployments that prioritise reliable delivery, the buffer is the right call.

### Delivery Status in the UI

The sender sees a per-message status indicator:

| Indicator | Meaning |
|---|---|
| `·` pending | Queued locally, recipient not yet seen |
| `⇡` buffered | Handed to server buffer, awaiting recipient |
| `✓` delivered | Received by recipient's client |
| `✗` expired | TTL elapsed (server buffer only), never delivered |

### IT Admin Configuration

**Server (`server.toml`):**

```toml
[buffer]
enabled  = false     # set true to enable server-side buffering
ttl_days = 7         # how long to hold undelivered messages
max_kb   = 512       # max message size accepted into buffer
```

**Client (`config.toml`):**

```toml
[queue]
enabled        = true   # client-side queue, always recommended
watch_ttl      = 60     # seconds to hold a presence watch subscription
retry_interval = 30     # seconds between re-registering a watch if it expires
```

The client auto-detects whether the server has buffering enabled on connect and adjusts behaviour accordingly — no manual client configuration needed to match the server's capability.

### Module

```
ezchat/
└── delivery/
    ├── queue.py       # local queue read/write, presence watch registration
    └── status.py      # per-message delivery state tracking and UI indicator

ezchat_server/
└── buffer.py          # server-side message buffer (only loaded if enabled)
```

---

## File Transfer

Users can send any file — images, PDFs, zip archives, documents — directly to a peer over the existing P2P connection. Files are end-to-end encrypted in transit and saved to a local download directory. Viewing is handled by the user's file browser or IDE (e.g. VSCode's Explorer panel) — the terminal shows transfer status only.

### Transfer Flow

```
/send report.pdf
  → read file, compute SHA-256 hash
    → send file_offer envelope to peer:
       { name: "report.pdf", size: 2.3MB, mime: "application/pdf", hash: "..." }

Peer sees in chat window:
  [FILE] @alice → report.pdf  2.3 MB  [Y]es / [N]o

Peer accepts (Y or /accept)
  → file read in chunks (default 64 KB)
    → each chunk encrypted with session key (unique nonce per chunk)
      → chunks streamed over P2P connection
        → peer reassembles and decrypts
          → SHA-256 verified against offered hash
            → saved to download directory
              → both sides see completion notice in chat
```

### Chat Window Appearance

```
[10:45] @alice:  here's the Q1 brief
[FILE]  @alice → report.pdf  2.3 MB          [Y]es / [N]o
[10:45] @bob:    accepting
[FILE]  report.pdf  [████████████░░░░]  75%  1.7 / 2.3 MB
[FILE]  ✓ report.pdf  2.3 MB  → ~/Downloads/ezchat/
```

Transfer progress is shown for both sender and receiver. The completion line shows the save path so the user knows exactly where to find the file.

### Viewing Received Files

Files are saved to `~/Downloads/ezchat/` (configurable). Users open them through whatever tool is natural for their environment — VSCode's Explorer sidebar, macOS Finder, a file manager. ezchat does not attempt to render file content in the terminal.

### Constraints

**Files are P2P only — no server buffer.** File transfers require both peers to be online simultaneously. Unlike text messages, files cannot be queued for offline delivery. Attempting to send a file to an offline peer shows an error and suggests sending a message instead.

**TURN relay warning.** If the connection is relaying through the TURN server rather than connecting directly (visible in the status bar), the UI warns before a large transfer begins:

```
[WARN] This connection is relayed — large transfers may be slow. Continue? [Y]es / [N]o
```

**No inline rendering.** The terminal displays filename, size, MIME type, and progress only. Image previews, PDF rendering, and file execution are out of scope — the file browser handles all of that.

### Envelope Types

Three new message types added to the existing framing protocol:

```json
{ "v": 1, "type": "file_offer",    "ts": "...", "body": "<encrypted offer metadata>" }
{ "v": 1, "type": "file_chunk",    "ts": "...", "body": "<encrypted chunk + sequence number>" }
{ "v": 1, "type": "file_complete", "ts": "...", "body": "<encrypted final hash confirmation>" }
```

Existing message types (`msg`, `ai_share`, `sys`) are unaffected. File chunks use the same AES-256-GCM session key as messages, with a unique 96-bit nonce per chunk.

### Commands

| Command | Behavior |
|---|---|
| `/send <path>` | Offer a file to the current peer |
| `/accept` | Accept an incoming file offer (or press `Y` at the prompt) |
| `/decline` | Decline an incoming file offer (or press `N`) |
| `/transfers` | Show active and completed transfers in the current session |

### Configuration

```toml
[files]
download_dir  = "~/Downloads/ezchat"   # where received files are saved
max_size_mb   = 500                    # refuse incoming offers above this size
auto_accept   = false                  # always prompt before accepting
chunk_kb      = 64                     # transfer chunk size
```

`auto_accept = true` can be set by users who trust their peers and don't want the confirmation prompt. IT admins may enforce `max_size_mb` at the server level in a future hardening pass.

### Module

```
ezchat/
└── files/
    ├── sender.py      # chunk, encrypt, stream outbound file
    └── receiver.py    # reassemble, decrypt, verify hash, write to disk
```

---

## Sound Notifications

ezchat plays a sound when chat events occur — a new message arrives, a peer comes online, a file transfer completes. All sounds are configurable; the client ships with a set of built-in retro tones so it works out of the box with no setup.

### Triggers

| Event | Default sound | Config key |
|---|---|---|
| New message received | `bbs_ping` | `new_message` |
| Peer comes online | `terminal_bell` | `peer_online` |
| Peer goes offline | *(silent)* | `peer_offline` |
| File transfer completed | `bbs_ping` | `file_received` |
| AI response ready | *(silent)* | `ai_ready` |

### Built-in Sounds

A small set of retro-themed tones ships inside the package — no external files required.

| Name | Description |
|---|---|
| `terminal_bell` | Classic ASCII BEL tone |
| `bbs_ping` | Short BBS-era notification ping |
| `modem_chirp` | Brief modem handshake chirp |
| `key_click` | Mechanical keyboard click |
| `silent` | Explicitly no sound |

### Custom Sounds

Any event can be pointed at a file on disk instead of a built-in tone. Supported formats: `.wav`, `.mp3`, `.ogg`.

```toml
[sounds]
enabled       = true
volume        = 0.8               # 0.0 – 1.0
new_message   = "bbs_ping"        # built-in name
peer_online   = "terminal_bell"
peer_offline  = ""                # empty = silent
file_received = "bbs_ping"
ai_ready      = ""
# custom file example:
# new_message = "/Users/alice/sounds/notify.wav"
```

### Commands

| Command | Behavior |
|---|---|
| `/sound off` | Mute all sounds for the session |
| `/sound on` | Unmute |
| `/sound <event> <name>` | Change a sound live (e.g. `/sound new_message modem_chirp`) |
| `/sound test` | Play all configured sounds in sequence |

Changes made with `/sound` apply immediately and persist to `config.toml`.

### Platform Library

`pygame.mixer` handles audio playback — reliable cross-platform support for `.wav`, `.mp3`, and `.ogg` on macOS, Linux, and Windows. It is imported lazily and only initialised if `sounds.enabled = true`, so users who don't want audio have zero overhead.

### Module

```
ezchat/
└── sounds/
    ├── player.py          # pygame.mixer wrapper, lazy init, volume control
    ├── registry.py        # resolve built-in name or file path to audio data
    └── builtin/           # built-in .wav files shipped with the package
        ├── terminal_bell.wav
        ├── bbs_ping.wav
        ├── modem_chirp.wav
        └── key_click.wav
```

---

## Games

Users can challenge their chat peer to a retro multiplayer game without leaving ezchat. Games render in the terminal using curses and inherit the active theme — every game looks native to whatever retro skin the user has chosen. Chat continues to receive messages in the background; returning from a game drops the user straight back into their conversation.

### Theme Integration

Games pull colours directly from the active theme at render time — no per-game colour configuration needed. A chess board in Phosphor Green looks different from the same board in C64 blue or Amber Terminal, and both look intentional.

```
Phosphor Green theme:          Amber Terminal theme:

  ♜ ♞ ♝ ♛ ♚ ♝ ♞ ♜             ♜ ♞ ♝ ♛ ♚ ♝ ♞ ♜
  ♟ ♟ ♟ ♟ ♟ ♟ ♟ ♟             ♟ ♟ ♟ ♟ ♟ ♟ ♟ ♟
  · · · · · · · ·             · · · · · · · ·
  · · · · · · · ·             · · · · · · · ·
  · · · · · · · ·             · · · · · · · ·
  · · · · · · · ·             · · · · · · · ·
  ♙ ♙ ♙ ♙ ♙ ♙ ♙ ♙             ♙ ♙ ♙ ♙ ♙ ♙ ♙ ♙
  ♖ ♘ ♗ ♕ ♔ ♗ ♘ ♖             ♖ ♘ ♗ ♕ ♔ ♗ ♘ ♖

  rendered in bright_green       rendered in amber
  on black background            on black background
```

The theme's `foreground`, `accent`, `background`, and `status_bg` colours map to game elements: board squares, active pieces, empty cells, and the status line showing whose turn it is.

### Game Framework

All games share a common base class. Each game is a self-contained plugin in `ezchat/games/`.

```python
class Game(ABC):
    def __init__(self, theme: Theme, peer_handle: str): ...

    async def on_start(self, i_go_first: bool) -> None: ...
    async def render(self, window) -> None: ...          # draw to curses window
    async def handle_input(self, key: int) -> None: ...  # local keypress
    async def handle_peer(self, event: dict) -> None: ... # incoming game event
    async def on_end(self, winner: str | None) -> None: ...
```

When a game is active it takes over the full terminal. The chat window is suspended but continues receiving messages silently. `ESC` or `/quit-game` ends the game (counts as a concede) and returns to chat with a summary line in the message history:

```
[GAME] Chess vs @bob — @bob won  (14 moves, 8 minutes)
```

### Built-in Games

| Game | Type | Description |
|---|---|---|
| **Pong** | Real-time | Two paddles, one ball; paddles rendered as `█` blocks in theme accent colour |
| **Chess** | Turn-based | Full rules; Unicode chess pieces; board squares in theme foreground/background |
| **Battleship** | Turn-based | Classic 10×10 grids; ships rendered in theme accent, hits in error colour |
| **Connect Four** | Turn-based | 7×6 grid; each player's pieces in distinct theme colours |
| **Hangman** | Turn-based | Word guessing; gallows drawn in ASCII; letters in theme foreground |
| **Tic-tac-toe** | Turn-based | 3×3 grid; simplest game, useful for testing the framework |

### Network Protocol

Game events use three new envelope types that slot into the existing message framing:

```json
{ "v": 1, "type": "game_invite",  "ts": "...", "body": "{ \"game\": \"chess\" }" }
{ "v": 1, "type": "game_event",   "ts": "...", "body": "{ \"move\": \"e2e4\" }" }
{ "v": 1, "type": "game_over",    "ts": "...", "body": "{ \"winner\": \"@alice\" }" }
```

All payloads are encrypted with the session key. Turn-based games send one `game_event` per move. Real-time games (Pong) send state updates at up to 30 fps over the existing P2P channel — fast enough for smooth play on a LAN or low-latency connection.

Accept/decline is handled by the existing UI prompt pattern — the same `[Y]es / [N]o` used for file transfers.

### Commands

| Command | Behavior |
|---|---|
| `/game <name>` | Challenge current peer (e.g. `/game chess`) |
| `/game list` | Show all available games |
| `/quit-game` | Concede and return to chat |

The peer sees:

```
[GAME] @alice is challenging you to Chess  [Y]es / [N]o
```

### Sound Integration

Games trigger the existing sound system. A move confirmation click, a win chime, and a loss tone are added as built-in sounds and configurable per-event in `config.toml`:

```toml
[sounds]
game_move = "key_click"
game_win  = "bbs_ping"
game_loss = ""
```

### Module

```
ezchat/
└── games/
    ├── base.py          # Game ABC, game loop, network event dispatch
    ├── pong.py          # real-time Pong
    ├── chess.py         # Chess (full rules)
    ├── battleship.py    # Battleship
    ├── connect_four.py  # Connect Four
    ├── hangman.py       # Hangman
    └── tictactoe.py     # Tic-tac-toe
```

---

## Headless Agents

The ezchat protocol places no restrictions on message semantics. A message is an encrypted UTF-8 string — what the receiver does with it is entirely up to the application. ezchat's job is secure delivery and identity; it has no opinion on what is inside the envelope.

This means any device that can run Python can participate as a headless agent: an IoT hub, a build server, a monitoring daemon, a home automation bridge. The agent — or the user connecting to it — defines whatever message format makes sense for their use case. ezchat does not define or impose a command protocol.

**The protocol does not need to change to support this.** Agents are first-class participants that happen to have no terminal UI.

### Headless Agent Mode

```bash
ezchat --agent --script handler.py
```

Starts ezchat without the curses UI. The network stack, encryption, and registry chain all function identically to a normal client. When a message arrives, `handler.py` is called with the sender handle and the raw message string. If the handler returns a string, it is sent back as a reply. The content and structure of those strings is entirely the handler's concern.

### Authentication

The `sender` parameter passed to every handler call is not a claim the peer makes about themselves — it is a cryptographically verified identity. The Ed25519 handshake completes before any message is exchanged, proving the connecting peer holds the private key for that handle. A random person cannot connect to your agent and claim to be `@alice` without Alice's private key.

This means ezchat identity is the authentication mechanism. Agents never manage passwords, API keys, or tokens.

**Layer 1 — Connection allowlist (agent config)**

The agent runner checks the connecting peer's verified handle against an allowlist before opening a message channel. Anyone not on the list is rejected at handshake time — the handler never sees the attempt:

```toml
[agent]
script          = "/path/to/handler.py"
allowed_handles = ["@alice", "@bob"]   # all other handles are rejected at connect time
```

**Layer 2 — Handler-level authorization**

For fine-grained per-command control inside the handler:

```python
ADMINS  = {"@alice"}
TRUSTED = {"@alice", "@bob"}

def on_message(sender: str, message: str) -> str | None:
    if sender not in TRUSTED:
        return None   # return nothing — give no information to unknown senders

    if message == "unlock front door" and sender not in ADMINS:
        return "Not authorised for that."

    # sender is trusted — handle the message
    ...
```

Returning `None` for unknown senders rather than an error is intentional — it reveals nothing to someone probing the agent.

**Why this is stronger than a password**

| | Password | ezchat identity |
|---|---|---|
| Proof of identity | Something you know | Something you have (private key) |
| Can be guessed | Yes | No — 256-bit key |
| Transmitted over the wire | Yes | Never |
| Can be shared accidentally | Yes | Only by deliberate key export |
| User effort | Type it every time | Nothing — automatic |

### Handler Interface

```python
# handler.py — define whatever protocol makes sense for your integration.
# ezchat delivers the string and a verified sender identity; you decide what to do with both.

def on_message(sender: str, message: str) -> str | None:
    # sender is cryptographically verified — safe to use for authorization decisions
    # parse, dispatch, and reply however your integration requires
    ...
    return response_string_or_none
```

The handler is a plain Python file with no ezchat-specific imports. It can use any library, speak any protocol, call any local or remote API. ezchat provides the encrypted transport and verified identity; the handler owns everything above that.

### Agent Registration

Agents register in the registry chain with `type: "agent"` — the only addition to the existing block structure:

```json
{
  "handle":       "@home-hub",
  "pubkey":       "...",
  "display_name": "Home Hub",
  "type":         "agent",
  "description":  "optional free-text description",
  "registered_at": "...",
  "sig":          "..."
}
```

Agents appear in the presence panel with `⚙` rather than `●`/`○` so users can distinguish them from people at a glance:

```
┌──────────────────┐
│ USERS  3 of 5 ▲  │
│                  │
│ ● @alice         │
│ ● @bob           │
│ ○ @carol         │
│ ⚙ @home-hub  ●  │   ← agent, online
│ ⚙ @build-bot ○  │   ← agent, offline
└──────────────────┘
```

Connecting to an agent with `/connect @home-hub` works identically to connecting to a person — same UI, same encryption, same presence indicators. The chat window carries whatever strings the two sides agree to exchange.

### Running as a Service

```bash
pip install ezchat
ezchat --agent --script /path/to/handler.py --server https://chat.internal:8443
```

On first run the agent generates its identity keypair and registers its handle. After that it runs silently as a background service using the same launchd/systemd setup described in the ezchat-server section.

### Configuration

```toml
[agent]
script          = "/path/to/handler.py"
description     = ""                    # optional, shown in registry
log_level       = "warn"                # logs to stdout/file, no UI
allowed_handles = ["@alice", "@bob"]    # empty list = reject all connections
```

`allowed_handles` is enforced at the connection layer before the handler is invoked. An empty list locks the agent completely — no one can connect until handles are explicitly added. This is the safe default for agents controlling sensitive hardware.

### Agent Archetypes

Four natural patterns emerge from the handler interface. All share the same underlying infrastructure — only the handler logic differs.

---

**1. Command/Response Agent**

Receives a message, performs an action, returns a result. The simplest pattern.

```python
def on_message(sender: str, message: str) -> str | None:
    if sender not in TRUSTED: return None
    if message == "lights on":
        call_home_assistant("turn_on")
        return "Lights on ✓"
```

Use cases: home automation, device control, sensor queries, anything with discrete commands.

---

**2. Remote Shell Agent**

Forwards messages to a local shell process and streams output back. Turns the ezchat chat window into a secure remote terminal — like SSH or Raspberry Pi Connect, but over the ezchat encrypted channel and gated by `allowed_handles`.

```python
import subprocess

_proc = None

def on_message(sender: str, message: str) -> str | None:
    global _proc
    if sender not in TRUSTED: return None

    if _proc is None:
        _proc = subprocess.Popen(
            ["/bin/bash"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )

    _proc.stdin.write((message + "\n").encode())
    _proc.stdin.flush()
    output = _proc.stdout.read1(4096).decode()
    return output or "(no output)"
```

From the chat window:

```
[10:42] @you:     ls /home/pi/tests
[10:42] @raspi:   test_gpio.py  test_sensors.py

[10:43] @you:     python test_gpio.py
[10:43] @raspi:   GPIO test passed ✓
```

The shell session is E2E encrypted end-to-end and requires no open ports, VPN, or Raspberry Pi Connect account — NAT traversal is handled by ezchat's ICE layer.

Use cases: headless Raspberry Pi access, remote test runners, server administration from the chat terminal.

---

**3. Notification / Push Agent**

Runs a background loop watching an external system and pushes messages into chat when something happens. The handler's `on_message` is optional — the agent can also send messages unprompted using the outbound message API.

```python
import asyncio

async def watch(send):
    while True:
        status = check_ci_pipeline()
        if status.changed:
            await send("@you", f"Build {status.id}: {status.result}")
        await asyncio.sleep(30)
```

Use cases: CI/CD build notifications, server health alerts, sensor threshold warnings, stock or API monitors.

---

**4. File Bridge Agent**

Receives a request message, locates a file, and uses the file transfer protocol to send it back. Gives teammates access to files on a shared machine without a shared drive or VPN.

```python
import os

SHARE_DIR = "/mnt/nas/shared"

def on_message(sender: str, message: str) -> str | None:
    if sender not in TRUSTED: return None
    if message.startswith("send "):
        filename = message.removeprefix("send ").strip()
        path = os.path.join(SHARE_DIR, filename)
        if os.path.exists(path):
            send_file(path)   # triggers ezchat file transfer to sender
            return f"Sending {filename}..."
        return f"Not found: {filename}"
```

Use cases: NAS access, shared asset libraries, log file retrieval.

---

### Community Agent Ecosystem

Because the handler interface is a single Python function with no ezchat-specific imports, agent implementations are trivially packageable and shareable. Anyone can publish a handler to PyPI:

```bash
pip install ezchat-agent-homeassistant
pip install ezchat-agent-shell
pip install ezchat-agent-cibot
pip install ezchat-agent-nas
pip install ezchat-agent-rpi-gpio
```

Each package ships a `handler.py` and whatever dependencies it needs. Packages expose a CLI entry point that wraps `ezchat --agent --script`:

```bash
ezchat-agent-shell --server https://chat.internal:8443 --handle @raspi
```

The agent registers on the network and immediately appears in the presence panel of everyone on the server. No new app, no new account, no new protocol.

The ezchat network becomes the control plane for anything headless. ezchat provides the identity, the encryption, and the NAT traversal. The handler provides the integration. Neither side needs to know anything about the other's internals.

Community handler authors should always check `sender` before acting on any message — the verified identity is there for exactly this purpose. Well-written community agents document which handles they expect in `allowed_handles` and what per-command authorization they enforce inside the handler.

### Module

```
ezchat/
└── agent/
    ├── runner.py      # headless event loop, no curses, calls handler script
    └── loader.py      # load and hot-reload handler.py from disk
```

---

## Private / Self-Hosted Deployment

This section describes the complete setup for a team that wants fully private, self-hosted chat with no data leaving their network.

### Topology

```
                        Company Network
  ┌──────────────────────────────────────────────────────┐
  │                                                      │
  │   Mac Mini (server)          User workstations       │
  │  ┌──────────────────┐       ┌──────┐  ┌──────┐      │
  │  │  ezchat-server   │       │Alice │  │ Bob  │      │
  │  │                  │       │      │  │      │      │
  │  │  STUN  :3478     │◄─────►│ezchat│  │ezchat│      │
  │  │  TURN  :3478     │       │      │  │      │      │
  │  │  API   :8443     │       └──────┘  └──────┘      │
  │  │  Chain sync      │                               │
  │  └──────────────────┘       ┌──────┐  ┌──────┐      │
  │                             │Carol │  │Dave  │      │
  │                             │      │  │      │      │
  │  Each user's machine:       │ezchat│  │ezchat│      │
  │  Ollama + local LLM         └──────┘  └──────┘      │
  │                                                      │
  └──────────────────────────────────────────────────────┘
                              │
                         (NAT/VPN)
                              │
                    Remote users (WFH)
                    connect via TURN relay
                    hosted on same server
```

### Server Setup (one-time, IT / admin)

```bash
# 1. Install ezchat on the server machine
pip install ezchat

# 2. Create server config
mkdir -p /etc/ezchat
cat > /etc/ezchat/server.toml << EOF
[server]
host     = "0.0.0.0"
api_port = 8443

[turn]
realm       = "company-internal"
credentials = [{username = "ezchat", password = "changeme"}]
EOF

# 3. Start the server (or install as a service — see above)
ezchat-server --config /etc/ezchat/server.toml
```

Note the server's internal IP address or hostname (e.g. `chat.company.internal` or `192.168.1.50`). This is the only piece of information users need.

### Client Setup (each user)

```bash
# 1. Install ezchat
pip install ezchat

# 2. Run once to generate identity and configure server
ezchat --server https://192.168.1.50:8443

# ezchat will:
#   - Generate your Ed25519 identity keypair
#   - Sync the registry chain from the server
#   - Prompt you to register a handle (e.g. @alice)
#   - Open the chat UI

# 3. (Optional) Save config so you don't need the flag each time
cat >> ~/.ezchat/config.toml << EOF

[rendezvous]
url = "https://192.168.1.50:8443"

[registry]
rendezvous_url = "https://192.168.1.50:8443"

[ai]
provider = "openai-compat"
api_key  = "none"
model    = "llama3.2"
base_url = "http://localhost:11434/v1"
EOF
```

### Local AI Setup (each user, optional)

Each user who wants AI features runs [Ollama](https://ollama.com) locally. On Apple Silicon Macs, models run entirely on the Neural Engine — fast, private, no internet required after the initial model pull.

```bash
# Install Ollama (macOS)
brew install ollama

# Pull a model (one-time, requires internet)
ollama pull llama3.2

# Ollama runs as a background service automatically
# It listens on http://localhost:11434 by default
```

After this, `/ai <prompt>` in ezchat sends the prompt to the local Ollama instance. Nothing leaves the machine.

### What Stays Completely Private

| Data | Stays on network? |
|---|---|
| All chat messages | Yes — E2E encrypted, server sees only ciphertext |
| User registry (who's on the system) | Yes — chain syncs only to/from self-hosted server |
| AI prompts and responses | Yes — routed to local Ollama instance |
| Peer connection endpoints | Yes — rendezvous server is self-hosted |
| STUN/TURN traffic | Yes — self-hosted server, no external STUN servers contacted |
| Identity keys | Yes — stored only in `~/.ezchat/identity.key` on each machine |

### Remote / WFH Users

Remote employees connect the same way — they just need network access to the server (VPN, or the server exposed on a known port):

```toml
[rendezvous]
url = "https://chat.company.com:8443"   # externally reachable hostname or IP
```

The TURN relay on the server handles NAT traversal for remote connections. Chat content remains E2E encrypted through the relay.

---

## Latency Testing & Benchmarking

Understanding where time is spent is essential for a chat system. ezchat ships with two latency tools: a lightweight inline command for spot-checking RTT during any session, and a full benchmark suite for systematic profiling.

### `/ping` — Inline RTT Measurement

Works in `--test` mode (measures echo bot round-trip) and real peer connections (measures actual P2P RTT). Breaks the result into encryption overhead vs network time so the source of latency is immediately obvious.

```
> /ping
[PING] @bob  RTT: 42ms   enc: 0.8ms   net: 41ms

> /ping 10
[PING] @bob  10 samples
  p50: 38ms   p95: 67ms   p99: 124ms   enc avg: 0.9ms
```

The encryption component is measured locally (time to encrypt + decrypt a round-trip payload). Network time is total RTT minus encryption overhead.

### `ezchat --bench` — Full Benchmark Suite

Runs a structured series of tests against a target and produces a latency report. The target is any reachable ezchat peer — the echo agent is the natural choice since it's a controlled reflector.

```bash
ezchat --bench --target @raspi
ezchat --bench --target @echobot        # local echo bot, no network
ezchat --bench --target localhost:9999  # direct address
```

Each section of the report only runs if the relevant feature is built. Phase 1 can benchmark crypto only; later phases add their sections automatically.

```
ezchat latency report — 2026-03-18 10:42
══════════════════════════════════════════════════════

[crypto]  AES-256-GCM encrypt+decrypt
  msg size    p50      p95      p99
  256 B       0.1ms    0.2ms    0.3ms
  1 KB        0.3ms    0.5ms    0.8ms
  64 KB       1.2ms    1.8ms    2.4ms

[messages]  Round-trip via echo agent  (100 samples)
  p50: 38ms    p95: 67ms    p99: 124ms
  enc overhead avg: 0.9ms  (2.4% of RTT)

[connection]  ICE setup time  (5 attempts)
  direct:      210ms
  hole-punch:  440ms
  relay:       890ms

[chain]  Registry chain operations
  sync 50 blocks:     120ms   (2.4ms/block)
  append + gossip:    18ms

[files]  Transfer throughput  (direct connection)
  1 MB:    8.2 MB/s
  10 MB:   9.1 MB/s
  100 MB:  9.4 MB/s

[ai]  Response latency  (local Ollama, llama3.2)
  p50: 1.2s    p95: 3.4s    p99: 5.1s

══════════════════════════════════════════════════════
bottleneck: network RTT (91% of message latency)
```

The final bottleneck line identifies the dominant latency source automatically.

### Timing Infrastructure

A lightweight timer module underlies both tools. It is available to all other modules for internal instrumentation — any subsystem can record a timing sample without pulling in a heavy profiling dependency.

```python
# ezchat/bench/timer.py
class Timer:
    def start(self, label: str) -> None: ...
    def stop(self, label: str) -> float: ...     # returns elapsed ms
    def percentiles(self, label: str) -> dict: ... # p50, p95, p99
    def report(self) -> str: ...
```

Used internally by the message router, crypto layer, and file transfer to record timing samples that feed into the `--bench` report. Zero cost when benchmarking is not active.

### What Gets Built in Each Phase

| Section | Available from |
|---|---|
| Crypto encrypt/decrypt | Phase 1 |
| `/ping` vs echo bot | Phase 1 |
| `/ping` vs real peer | Phase 2 |
| ICE setup timing | Phase 3 |
| Chain sync timing | Phase 4 |
| File transfer throughput | Phase 7 |
| AI response latency | Phase 6 |

### Module

```
src/ezchat/
└── bench/
    ├── timer.py       # lightweight timing primitives used across all modules
    ├── ping.py        # /ping command implementation
    └── suite.py       # --bench suite runner and report formatter
```

---

## Test Mode

ezchat provides two test modes for development and debugging. Both eliminate the need to run two full client instances to simulate a conversation.

### Mode 1: Loopback Echo (`--test`)

The simplest mode. A single ezchat process starts with a built-in `@echobot` peer that automatically echoes every message back. No second window, no second process, no network required.

```bash
ezchat --test
```

The UI looks and behaves exactly like a real chat session:

```
┌──────────────────────────────────────────────────────┐
│ ezchat  [TEST MODE]  connected to @echobot            │
├──────────────────────────────────────────────────────┤
│                                                      │
│  [10:42] @you:      hello there                      │
│  [10:42] @echobot:  hello there                      │
│  [10:42] @you:      /ai what is rust?                │
│  [AI]    Rust is a systems programming language...   │
│  [10:43] @you:      /ai-share                        │
│  [10:43] @echobot:  [AI-SHARE received and echoed]   │
│                                                      │
├──────────────────────────────────────────────────────┤
│ > _                                                  │
└──────────────────────────────────────────────────────┘
```

`@echobot` echoes every message type — plain text, `/ai-share` blocks, system messages — so the full rendering pipeline can be exercised from a single window.

**Optional flags:**

```bash
ezchat --test --echo-delay 500    # simulate 500ms round-trip latency (ms)
ezchat --test --echo-script responses.txt  # reply with scripted lines instead of echoing
```

`responses.txt` is a plain text file, one response per line. `@echobot` cycles through them in order, then wraps. Useful for testing rendering of varied message lengths, unicode, etc.

`@echobot` is implemented entirely in `ezchat/test/echobot.py` as an `asyncio` task that satisfies the same interface as a real peer connection — no special-casing needed in the message router or UI.

### Mode 2: Headless Echo Agent (`--echo-server`)

A headless process that listens for a real ezchat connection and echoes everything back over the actual network stack. Useful for testing the full path: ICE negotiation, encryption handshake, framing, and message delivery.

`--echo-server` is the agent runner with a built-in echo handler — the simplest possible handler, shipping inside the package. No script file required:

```python
# built-in echo handler (ships inside ezchat/agent/)
def on_message(sender: str, message: str) -> str | None:
    return message  # ack by echoing
```

`--echo-server` and `--agent` share the same code path. The echo behaviour is just the degenerate case of an agent handler. This means the test infrastructure and the IoT integration infrastructure are the same thing.

```bash
# Terminal 1 — start the echo agent
ezchat --echo-server

# Terminal 2 — connect to it
ezchat --connect <host:port>
```

Logs received/sent message counts to stdout. Exits cleanly when the peer disconnects.

### What Test Mode Exercises

| Feature | `--test` | `--echo-server` |
|---|---|---|
| Message rendering | Yes | Yes (client side) |
| Theme display | Yes | Yes (client side) |
| AI integration (`/ai`, `/ai-share`) | Yes | Yes |
| Encryption handshake | Simulated | Real |
| ICE / NAT traversal | No | Real |
| Network framing | Simulated | Real |
| Multi-message latency | Simulated (`--echo-delay`) | Real |

### Module

```
ezchat/
└── test/
    └── echobot.py       # built-in loopback peer for --test mode only
                         # --echo-server uses ezchat/agent/ with a built-in echo handler
```

---

## Data Flow

### Startup

```
ezchat launches
  → identity.py: load or generate Ed25519 keypair
    → registry/chain.py: sync chain from rendezvous server
      → [if not registered] prompt user to register handle
        → registry/chain.py: append signed block, gossip to rendezvous
          → UI opens
```

### Sending a Message

```
User types message → Input bar
  → Message Router (plain text? command?)
    → Encryption Layer: encrypt with session key
      → P2P Network Layer: frame + send
        → [optional, if msg_anchoring=true] Registry Chain: append msg_anchor block
```

### Receiving a Message

```
P2P Network Layer: receive frame + parse envelope
  → Encryption Layer: decrypt with session key
    → Message Router: classify type (msg, ai_share, sys)
      → Curses UI Layer: append to chat window
        → [optional, if msg_anchoring=true] Registry Chain: append msg_anchor block
```

### AI Flow

```
User: /ai <prompt>
  → Message Router → AI Interface
    → HTTP call to LLM provider API
      → Response cached in AIInterface.last_exchange
        → Curses UI: display response locally (ai_fg color)

User: /ai-share
  → Message Router → AI Interface: retrieve last_exchange
    → Encryption Layer: encrypt ai_share envelope
      → P2P Network Layer: send to peer
        → Peer UI: render as [AI-SHARE] block
```

---

## Module Structure

```
ezchat/                          # repo root
│
├── src/                         # all source code lives here (src layout)
│   │
│   ├── ezchat_server/           # server package  →  ezchat-server command
│   │   ├── __main__.py          # entry point
│   │   ├── config.py            # server config loader
│   │   ├── stun.py              # STUN server (RFC 5389, asyncio UDP)
│   │   ├── turn.py              # TURN relay (asyncio UDP/TCP)
│   │   ├── rendezvous.py        # HTTPS API: peer register/lookup, presence watches
│   │   ├── buffer.py            # server-side message buffer (only loaded if enabled)
│   │   └── chain_api.py         # HTTPS API: chain sync endpoint
│   │
│   └── ezchat/                  # client package  →  ezchat command
│       ├── __main__.py          # entry point, CLI arg parsing
│       ├── config.py            # load/save ~/.ezchat/config.toml
│       ├── identity.py          # Ed25519 keypair generation and persistence
│       │
│       ├── network/
│       │   ├── ice.py           # aiortc ICE connection setup, candidate negotiation
│       │   ├── rendezvous.py    # register/lookup against the rendezvous server
│       │   └── framing.py       # length-prefix framing, envelope serialization
│       │
│       ├── crypto/
│       │   ├── handshake.py     # X25519 key exchange, identity verification
│       │   └── session.py       # AES-256-GCM encrypt/decrypt per message
│       │
│       ├── ui/
│       │   ├── app.py           # main curses application loop
│       │   ├── widgets.py       # chat window, input bar, status bar, presence panel
│       │   └── theme.py         # theme loader, color pair registry
│       │
│       ├── commands/
│       │   └── router.py        # parse and dispatch /ai, /ai-share, /theme, /quit …
│       │
│       ├── ai/
│       │   ├── base.py          # AIProvider ABC
│       │   ├── anthropic.py     # AnthropicProvider
│       │   └── openai.py        # OpenAIProvider / OpenAICompatProvider
│       │
│       ├── registry/
│       │   ├── chain.py         # RegistryChain: append, sync, verify, list_users
│       │   ├── block.py         # Block dataclass, hash/sign/validate logic
│       │   └── gossip.py        # broadcast new blocks to rendezvous + peers
│       │
│       ├── delivery/
│       │   ├── queue.py         # local queue, presence watch registration
│       │   └── status.py        # per-message delivery state and UI indicator
│       │
│       ├── files/
│       │   ├── sender.py        # chunk, encrypt, stream outbound file
│       │   └── receiver.py      # reassemble, decrypt, verify hash, write to disk
│       │
│       ├── bench/
│       │   ├── timer.py         # lightweight timing primitives, used across all modules
│       │   ├── ping.py          # /ping command implementation
│       │   └── suite.py         # --bench suite runner and report formatter
│       │
│       ├── agent/
│       │   ├── runner.py        # headless event loop, calls handler script
│       │   └── loader.py        # load and hot-reload handler.py from disk
│       │
│       ├── sounds/
│       │   ├── player.py        # pygame.mixer wrapper, lazy init, volume control
│       │   ├── registry.py      # resolve built-in name or file path to audio data
│       │   └── builtin/         # .wav files shipped with the package
│       │
│       ├── games/
│       │   ├── base.py          # Game ABC, game loop, network event dispatch
│       │   ├── pong.py          # real-time Pong
│       │   ├── chess.py         # Chess (full rules)
│       │   ├── battleship.py    # Battleship
│       │   ├── connect_four.py  # Connect Four
│       │   ├── hangman.py       # Hangman
│       │   └── tictactoe.py     # Tic-tac-toe
│       │
│       ├── test/
│       │   └── echobot.py       # built-in loopback peer for --test mode
│       │
│       └── themes/              # built-in theme TOML files
│           ├── phosphor_green.toml
│           ├── amber.toml
│           ├── c64.toml
│           ├── ansi_bbs.toml
│           └── paper_white.toml
│
├── examples/
│   └── agents/                  # agent archetype examples
│       ├── README.md
│       ├── command_response.py  # archetype 1: command / response
│       ├── remote_shell.py      # archetype 2: remote shell (Raspberry Pi etc.)
│       ├── notification_push.py # archetype 3: background watch + push
│       └── file_bridge.py       # archetype 4: file server bridge
│
└── docs/
    ├── ARCHITECTURE.md
    ├── PHASES.md
    └── PROTOCOL.md              # (Phase 8) language-agnostic wire format spec
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `cryptography` | X25519 DH, Ed25519 signing, AES-256-GCM |
| `aiortc` | ICE, STUN, and TURN — UDP hole punching and relay fallback |
| `aiohttp` | HTTPS calls to the rendezvous server |
| `tomllib` / `tomli` | Config and theme file parsing (stdlib in Python 3.11+) |
| `anthropic` | Anthropic LLM API client (optional) |
| `openai` | OpenAI-compatible API client (optional) |
| *(none)* | Registry chain is pure Python — `cryptography` covers all hashing and signing |
| `pygame` | Audio playback for sound notifications (optional, lazy-loaded) |
| `windows-curses` | curses on Windows (optional, platform dep) |

Required: `cryptography`, `aiortc`, `aiohttp`. All others are optional and only loaded when their feature is configured.

---

## Open Questions

1. ~~**NAT traversal:**~~ Resolved — stateless rendezvous server for peer discovery, `aiortc` ICE for UDP hole punching, TURN relay as encrypted fallback. See [NAT Traversal & Rendezvous](#nat-traversal--rendezvous).

2. ~~**Blockchain chain choice:**~~ Resolved — built-in Merkle registry chain, pure Python, no external node or gas. See [Registry Chain](#registry-chain).

3. ~~**Private deployment / server setup:**~~ Resolved — `ezchat-server` command ships in the same package; single-command server and client setup; AI runs via local Ollama. See [ezchat-server](#ezchat-server) and [Private / Self-Hosted Deployment](#private--self-hosted-deployment).

4. **Message history persistence:** Should chat logs be stored locally (encrypted at rest)? If so, where and in what format? Should the optional message anchor chain be the only durable record?

5. **Multi-provider AI routing:** Should users be able to configure multiple LLM providers and switch between them mid-session with `/ai-provider <name>`?

6. **Theme discovery:** Should ezchat support downloading community themes from a URL or a simple registry? What format should themes be distributed in?

7. **Key verification UX:** How should users verify they are talking to the right person (short authentication string, QR code, out-of-band fingerprint display)?
