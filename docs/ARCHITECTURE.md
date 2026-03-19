# ezchat Architecture

A peer-to-peer, end-to-end encrypted terminal chat platform with AI integration, a retro curses UI, and optional blockchain features.

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
9. [Blockchain Integration](#blockchain-integration)
10. [Data Flow](#data-flow)
11. [Module Structure](#module-structure)
12. [Open Questions](#open-questions)

---

## Overview

ezchat is a Python terminal application that enables direct, encrypted peer-to-peer chat between two users without a central server. It renders a retro-style curses interface that users can skin with classic terminal aesthetics. Users may optionally configure an LLM API key to interact with AI inline during chat, and share those AI exchanges with their peer. An optional blockchain layer provides tamper-evident message logging and decentralized identity anchoring.

---

## Goals & Non-Goals

### Goals

- Direct P2P connections — no central server required for messaging; a stateless rendezvous server assists with NAT traversal only
- End-to-end encryption on all messages
- Terminal UI built with `curses`, skinnable with multiple retro themes
- `/ai <prompt>` — send a prompt to a configured LLM and display the response privately
- `/ai-share` — share the last AI prompt and response into the chat with the peer
- Optional blockchain integration for identity anchoring and tamper-evident logs
- Simple onboarding: run the tool, get a peer address, share it, connect
- Provably stateless rendezvous server — no message content, no persistent storage, open source so anyone can self-host

### Non-Goals

- Group chat (multi-party) — out of scope for v1
- Mobile or GUI clients
- Media or file transfer — text only for v1
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
| **Blockchain Client** | Optionally anchor identity and log message hashes to a chain |

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

Users store their LLM API key in `~/.ezchat/config.toml`:

```toml
[ai]
provider = "anthropic"   # anthropic | openai | openai-compat
api_key  = "sk-..."
model    = "claude-sonnet-4-6"
base_url = ""            # optional, for openai-compat providers
```

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

## Blockchain Integration

Blockchain features are **optional** and off by default. They add trust and auditability without requiring a central server.

### Use Cases

#### 1. Decentralized Identity Anchoring

A user's Ed25519 public key (their identity) can be published to a blockchain as an on-chain record. This allows peers to verify identity without a central directory.

- **Approach:** Post the public key + a human-readable handle to a smart contract or via OP_RETURN on Bitcoin, or use a purpose-built identity chain (e.g., Handshake, ENS, or a local testnet).
- **Result:** Peers can look up `@alice` and retrieve her verified public key from the chain instead of needing out-of-band key exchange.

#### 2. Tamper-Evident Message Log

Each message's hash can be written to a blockchain to create an immutable transcript that neither party can later deny or alter.

- **Approach:** After each message is sent/received, compute `SHA-256(timestamp + sender_pubkey + ciphertext)` and periodically batch-anchor these hashes to a chain (to keep costs low).
- **Result:** Either party can prove a message was sent at a given time, and that it has not been modified.

#### 3. Micropayment / Token-Gated Features (exploratory)

- Users could stake a small amount of crypto as a spam-prevention mechanism (pay-to-chat).
- AI API costs could theoretically be split via a payment channel.
- This is highly exploratory and would require a Layer-2 or low-fee chain.

### Blockchain Abstraction

A `BlockchainClient` interface isolates chain-specific logic:

```python
class BlockchainClient(ABC):
    async def publish_identity(self, handle: str, pubkey: bytes) -> str: ...
    async def resolve_identity(self, handle: str) -> bytes | None: ...
    async def anchor_hash(self, data_hash: bytes) -> str: ...
```

Planned concrete implementations:
- `EthereumClient` — uses `web3.py`, targets a testnet (Sepolia) or L2 (Base, Arbitrum)
- `NullBlockchainClient` — no-op, used when blockchain is disabled

### Configuration

```toml
[blockchain]
enabled  = false
provider = "ethereum"
rpc_url  = "https://sepolia.infura.io/v3/<key>"
contract = "0x..."
wallet_key = ""   # private key for signing transactions; keep secure
```

---

## Data Flow

### Sending a Message

```
User types message → Input bar
  → Message Router (plain text? command?)
    → Encryption Layer: encrypt with session key
      → P2P Network Layer: frame + send over TCP
        → [optional] Blockchain Client: hash + anchor
```

### Receiving a Message

```
P2P Network Layer: receive frame + parse envelope
  → Encryption Layer: decrypt with session key
    → Message Router: classify type (msg, ai_share, sys)
      → Curses UI Layer: append to chat window
        → [optional] Blockchain Client: verify hash
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
ezchat/
├── __main__.py          # entry point, CLI arg parsing (argparse)
├── config.py            # load/save ~/.ezchat/config.toml
├── identity.py          # Ed25519 keypair generation and persistence
│
├── network/
│   ├── __init__.py
│   ├── ice.py           # aiortc ICE connection setup, candidate negotiation
│   ├── rendezvous.py    # register/lookup against the stateless rendezvous server
│   └── framing.py       # length-prefix framing, envelope serialization
│
├── crypto/
│   ├── __init__.py
│   ├── handshake.py     # X25519 key exchange, identity verification
│   └── session.py       # AES-256-GCM encrypt/decrypt per message
│
├── ui/
│   ├── __init__.py
│   ├── app.py           # main curses application loop
│   ├── widgets.py       # chat window, input bar, status bar
│   └── theme.py         # theme loader, color pair registry
│
├── commands/
│   ├── __init__.py
│   └── router.py        # parse and dispatch /, /ai, /ai-share, /theme, /quit
│
├── ai/
│   ├── __init__.py
│   ├── base.py          # AIProvider ABC
│   ├── anthropic.py     # AnthropicProvider
│   └── openai.py        # OpenAIProvider / OpenAICompatProvider
│
├── blockchain/
│   ├── __init__.py
│   ├── base.py          # BlockchainClient ABC
│   ├── ethereum.py      # EthereumClient (web3.py)
│   └── null.py          # NullBlockchainClient (no-op)
│
└── themes/              # built-in theme TOML files
    ├── phosphor_green.toml
    ├── amber.toml
    ├── c64.toml
    ├── ansi_bbs.toml
    └── paper_white.toml
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
| `web3` | Ethereum blockchain interaction (optional) |
| `windows-curses` | curses on Windows (optional, platform dep) |

Required: `cryptography`, `aiortc`, `aiohttp`. All others are optional and only loaded when their feature is configured.

---

## Open Questions

1. ~~**NAT traversal:**~~ Resolved — stateless rendezvous server for peer discovery, `aiortc` ICE for UDP hole punching, TURN relay as encrypted fallback. See [NAT Traversal & Rendezvous](#nat-traversal--rendezvous).

2. **Blockchain chain choice:** Ethereum testnets are free but require managing a wallet. Is there a simpler chain or protocol (e.g., Nostr, a local devnet) better suited for identity anchoring in early versions?

3. **Message history persistence:** Should chat logs be stored locally (encrypted at rest)? If so, where and in what format? Should the blockchain anchor be the only durable record?

4. **Multi-provider AI routing:** Should users be able to configure multiple LLM providers and switch between them mid-session with `/ai-provider <name>`?

5. **Theme discovery:** Should ezchat support downloading community themes from a URL or a simple registry? What format should themes be distributed in?

6. **Key verification UX:** How should users verify they are talking to the right person (short authentication string, QR code, out-of-band fingerprint display)?
