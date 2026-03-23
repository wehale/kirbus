# ezchat

A peer-to-peer, end-to-end encrypted terminal chat with built-in AI integration.

- **Private by design** — messages are encrypted between peers; no server ever sees content
- **No accounts** — identity is an Ed25519 keypair generated on first run
- **Zero-config start** — connect to the public registry and pick a server, no URLs needed
- **Works anywhere** — direct LAN connections or through a relay server for internet use
- **Local AI** — `/ai` command talks to a local Ollama instance; AI context is shared between peers
- **Retro terminal UI** — five built-in themes, channel support, scratch pad

---

## Quick start

```bash
git clone https://github.com/wehale/ezchat.git
cd ezchat
uv run ezchat --handle yourname
```

That's it. The client connects to the default registry at `ezchat.kirbus.ai`, shows you available servers, and you pick one with Tab + Enter.

Requires Python 3.11+ and [uv](https://github.com/astral-sh/uv). Or install system-wide with pip:

```bash
pip install -e .
```

After `pip install`, commands like `ezchat`, `ezchat-server`, and `ezchat-registry` are available directly. If running from the repo with `uv` instead, prefix all commands with `uv run` (e.g. `uv run ezchat`, `uv run ezchat-server`).

---

## LAN mode (no server needed)

```bash
# Terminal 1 — listen
ezchat --handle alice --listen 9000

# Terminal 2 — connect
ezchat --handle bob --connect localhost:9000
```

---

## Registry

The registry is a public directory of ezchat servers. The default registry is `https://ezchat.kirbus.ai`. When you run `ezchat --handle yourname`, it fetches the server list and lets you pick one.

To use a different registry:

```bash
ezchat --handle yourname --registry https://custom.example.com
```

To skip the registry and connect directly to a known server:

```bash
ezchat --handle yourname --server http://SERVER_IP:8000
```

---

## Running your own server

One person runs `ezchat-server` on a machine with a public IP. Everyone else connects through the registry or via `--server`.

```bash
ezchat-server --config server.toml
```

Open ports **8000** (rendezvous API) and **9001** (TCP relay) in your firewall.

Example `server.toml`:

```toml
[server]
host       = "0.0.0.0"
api_port   = 8000
relay_port = 9001
ttl        = 60
log_level  = "info"

[registry]
url         = "https://ezchat.kirbus.ai"
name        = "my-server"
description = "A public ezchat server"
secret      = "CHANGE_ME"
access      = "open"
public_url  = "http://YOUR_PUBLIC_IP:8000"

[auth]
mode = "open"
```

### Server access modes

| Mode | Description |
|------|-------------|
| `open` | Anyone can join |
| `password` | Password required on first connect; pubkey saved for future access |
| `allowlist` | Only pre-approved pubkeys can connect |

For password-protected servers, add to `server.toml`:

```toml
[auth]
mode     = "password"
password = "your-server-password"
```

### Superuser (admin)

Connect from the same machine as the server with the `--su` flag:

```bash
ezchat --handle admin --su
```

Su users get admin commands: `/kick`, `/ban`, `/unban`, `/who`.

---

## Running your own registry

```bash
ezchat-registry --config registry.toml
```

Example `registry.toml`:

```toml
[registry]
host          = "0.0.0.0"
port          = 8080
heartbeat_ttl = 180
log_level     = "info"
```

Servers register themselves via heartbeat. The registry is stateless — listings live in memory and rebuild from heartbeats.

---

## Encrypted history

Encrypt chat logs at rest with a passphrase:

```bash
ezchat --handle yourname --encrypt-history
```

First run prompts you to set a passphrase. Subsequent runs prompt for the passphrase to unlock history. The passphrase is never stored — without it, the history files are unreadable.

To decrypt history for export:

```bash
ezchat --decrypt-history @alice > alice.log
ezchat --decrypt-history '#general' > general.log
```

To disable encryption and decrypt everything back to plaintext:

```bash
ezchat --handle yourname --no-encrypt-history
```

---

## Multiple identities

Each `--handle` gets its own data directory (`~/.ezchat-{handle}/`) with its own keypair, peers, and history:

```bash
ezchat --handle work-me
ezchat --handle personal-me
```

Override with `EZCHAT_HOME`:

```bash
EZCHAT_HOME=~/.ezchat-custom ezchat --handle custom
```

---

## Configuration

`~/.ezchat-{handle}/config.toml` — created automatically on first run.

```toml
[ui]
theme  = "ansi_bbs"        # phosphor_green | amber_terminal | c64 | ansi_bbs | paper_white
handle = "you"
encrypt_history = false

[ai]
provider = "openai-compat"
model    = "gemma3:4b"
base_url = "http://localhost:11434/v1"
api_key  = ""
```

---

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/ai <prompt>` | Ask the AI; response shown in conversation |
| `/ai-peer` | Forward the last peer message to your local AI |
| `/theme <name>` | Switch theme |
| `/themes` | List available themes |
| `/accept [peer]` | Accept a new or key-changed peer |
| `/block [peer]` | Mark a peer as blocked |
| `/unblock [peer]` | Remove blocked mark |
| `/servers` | Refresh server list from registry |
| `/connect <name>` | Connect to a server by name |
| `/disconnect` | Leave current server, return to server list |
| `/channel create <name>` | Create a channel |
| `/channel join <name>` | Join a channel |
| `/channel invite <peer> [channel]` | Invite a peer to a channel |
| `/channel leave <name>` | Leave a channel |
| `/clear` | Clear chat history |
| `/quit` | Exit |

**Su commands** (admin only):

| Command | Description |
|---------|-------------|
| `/kick <handle>` | Disconnect a peer |
| `/ban <handle>` | Kick and revoke access |
| `/unban <handle>` | Restore access |
| `/who` | List connected peers with details |

**Keyboard shortcuts:**

| Key | Action |
|-----|--------|
| `Tab` | Focus peer list |
| `↑` / `↓` | Navigate peers or command history |
| `Enter` | Select peer / send message |
| `Esc` | Return focus to input |
| `PgUp` / `PgDn` | Scroll chat |
| Mouse wheel | Scroll chat |

---

## AI integration

ezchat uses [Ollama](https://ollama.com) for local AI.

```bash
# Install Ollama, then pull a model
ollama pull gemma3:4b

# Ask the AI in any conversation
/ai what's the capital of France?
```

AI context is shared between peers — if alice asks a question and bob follows up, the AI sees the full conversation history.

`/ai-peer` grabs the last message from your peer and forwards it to your AI automatically.

Each person's `/ai` runs against their own local model. For cloud AI, point `base_url` at any OpenAI-compatible endpoint and set `api_key`.

**WSL2 note:** if Ollama is running on Windows, set `OLLAMA_HOST=0.0.0.0` before starting it and point `base_url` at the Windows host IP (find it with `ip route | grep default | awk '{print $3}'`).

---

## Verify message signatures

Every message is signed with the sender's Ed25519 key and stored in `~/.ezchat-{handle}/history/`.

```bash
ezchat --verify-log @alice
ezchat --verify-log '#general'
ezchat --verify-log scratch
```

---

## Test mode

Try the UI without any network setup:

```bash
ezchat --test
```

Simulated peers come online, join channels, and respond to messages.

---

## Deploy to AWS

A CDK stack is included in `deploy/` to provision an EC2 instance with the registry and a lobby server:

```bash
cd deploy
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk deploy -c key_name=your-ssh-key
```

The stack creates an EC2 instance, Elastic IP, security group, nginx reverse proxy, and Let's Encrypt TLS. See `deploy/ezchat_stack.py` for details.

---

## Security model

- **Identity** — Ed25519 keypair, generated locally, never leaves your machine
- **Key exchange** — X25519 ECDH ephemeral keys per session
- **Encryption** — AES-256-GCM with HKDF-derived keys
- **Message signing** — every message signed by sender's Ed25519 key
- **History encryption** — optional AES-256-GCM at rest with scrypt-derived key
- **Server auth** — password gate + pubkey allowlist for access control
- **Relay** — the relay server pipes opaque ciphertext; it cannot read messages
- **Rendezvous** — registrations are signed; the server stores handle → IP:port for 60 seconds then discards
- **Registry** — stateless directory; never touches chat traffic

Self-host the server and registry for full sovereignty.
