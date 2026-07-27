# CabalSpy MCP server — KOL and smart money wallet tracking for AI assistants

[![Smithery](https://img.shields.io/badge/Smithery-listed-blueviolet?style=flat-square)](https://smithery.ai/servers/cabalspy)
[![Glama](https://img.shields.io/badge/Glama-listed-blue?style=flat-square)](https://glama.ai/mcp/servers/CabalSpy/CabalSpy-MCP-Server)
[![MCP](https://img.shields.io/badge/MCP-compatible-blueviolet?style=flat-square)](https://modelcontextprotocol.io/)
[![Chains](https://img.shields.io/badge/chains-5-brightgreen?style=flat-square)](#chain-coverage)
[![Tools](https://img.shields.io/badge/tools-21-brightgreen?style=flat-square)](#tools)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)

Realtime **KOL API** and onchain wallet tracking for AI assistants. CabalSpy monitors labeled wallets — key opinion leaders (KOLs), smart money and whales — across **Solana, Base, BNB Chain, Ethereum and Robinhood Chain**, and exposes the data as Model Context Protocol tools.

Connect it to Claude, Cursor, or any MCP client and ask about onchain trading activity in plain language. No code, no SDK, no integration work.

**What people use it for:** vetting a KOL call before following it, checking whether a launch was bundled, finding which wallets accumulate together, building copy-trading shortlists, and answering "who is this address" in one line.

**The multichain one.** Most onchain KOL tooling is Solana only. CabalSpy tracks labeled wallets on
five chains — Solana, Base, BNB Chain, Ethereum and Robinhood Chain — through one connection and one
set of tools. The same question works everywhere: *"who bought this?"*

Powering labeled-wallet data inside Axiom, Trojan, o1.exchange and 20+ other trading tools.

- **Remote endpoint:** `https://mcp.cabalspy.xyz/mcp`
- **Transport:** Streamable HTTP
- **Auth:** per-user API key via the `X-CabalSpy-Key` header
- **Free test key:** 1000 requests at [apidashboard.cabalspy.xyz](https://apidashboard.cabalspy.xyz/)
- **Pricing:** [cabalspy.xyz/pricing](https://cabalspy.xyz/pricing)

## Chain coverage

| Chain | Identifier | Currency | Wallet types |
|---|---|---|---|
| Solana | `solana` | SOL | kol, smart, whale |
| Base | `base` | ETH | kol, smart |
| BNB Chain | `bnb` | BNB | kol, smart |
| Ethereum | `eth` | ETH | kol |
| Robinhood Chain | `rh` | ETH | kol, smart |

### KOL tracking on Solana

The deepest coverage of the five. Solana is the only chain with whale wallets, live market cap, pump.fun bonding curve progress, and `detect_bundles`, which finds KOL wallets buying through Jito bundles alongside side wallets they control.

> *"Was this token bundled?"* · *"Which whales are accumulating right now?"*

### KOL tracking on Base

Both kol and smart wallets, denominated in ETH. EVM address format.

> *"Which Base smart money wallets are up the most this month?"*

### KOL tracking on BNB Chain

Both kol and smart wallets, denominated in BNB.

> *"What are BNB Chain KOLs buying today?"*

### KOL tracking on Ethereum

Mainnet carries kol wallets only. Smart money signals are unavailable there.

> *"Show me the Ethereum KOL leaderboard for the last 7 days."*

### KOL tracking on Robinhood Chain

Robinhood Chain is Robinhood's Ethereum L2 on the Arbitrum Orbit stack, with ETH as the gas token. Both kol and smart wallets are tracked.

> *"How much volume did Robinhood Chain KOLs do in the last 24 hours?"*

## Tools

21 tools covering the full v1 API. All read-only.

### Wallets
| Tool | What it does |
|---|---|
| `lookup_wallet` | Identify an address across all chains and wallet types |
| `get_wallet_tracker` | Realized PnL, win rate, volume, trade counts for one wallet |
| `get_leaderboard` | Top wallets by performance for a chain, type and period |
| `list_wallets` | Browse all tracked wallets for a chain and type |
| `get_wallet_history` | Lifetime trading history, paginated, per token |
| `get_wallet_holdings` | Current onchain positions, read live |
| `get_pnl_calendar` | Daily and monthly realized profit and loss |
| `get_wallet_connections` | Wallets that trade the same tokens |
| `compare_wallets` | Up to 100 wallets in one request |

### Tokens
| Tool | What it does |
|---|---|
| `get_token_stats` | Who traded a token, buying pressure, entries |
| `get_token_holders` | Who still holds it, with market cap on Solana |
| `get_token_transactions` | Individual buys and sells, most recent first |
| `compare_tokens` | Up to 100 tokens in one request |
| `detect_bundles` | Jito bundle detection with confidence and evidence. Solana only |

### Market activity
| Tool | What it does |
|---|---|
| `get_recent_trades` | The live feed, optionally windowed to the last N minutes |
| `get_activity_metrics` | Trade count, unique wallets and volume over up to 24 hours |
| `get_signals` | Cluster, entry and exit signals |
| `get_signal_history` | Past signals for backtesting |
| `get_analytics` | Volume trend, most traded, win rate, top performers |

### Onboarding
| Tool | What it does |
|---|---|
| `get_started` | Free key, pricing, coverage and the data caveats |
| `get_api_status` | Health and what the API currently covers |

## Questions it answers

- *"Who are the best performing Solana KOLs today?"*
- *"Was this token launch bundled?"*
- *"What are KOLs buying right now?"*
- *"Who is still holding this token, and who already sold?"*
- *"Which wallets trade similar tokens to this address?"*
- *"Compare these five wallets over 30 days."*

## Connecting

### claude.ai (web)

The web connector cannot send custom headers — it only speaks OAuth. Put the key in the URL instead:

```
https://mcp.cabalspy.xyz/mcp?api_key=your_key
```

Settings → Connectors → Add custom connector, paste that URL, and leave the OAuth client fields **empty**. Filling them starts an OAuth flow this server does not implement, and you get a 404 on `/authorize`.

### Claude Desktop

Claude Desktop reads a config file, so the header works and is preferred:

```json
{
  "mcpServers": {
    "cabalspy": {
      "type": "http",
      "url": "https://mcp.cabalspy.xyz/mcp",
      "headers": { "X-CabalSpy-Key": "your_key" }
    }
  }
}
```

### Cursor, VS Code and others

```json
{
  "mcpServers": {
    "cabalspy": {
      "type": "http",
      "url": "https://mcp.cabalspy.xyz/mcp",
      "headers": { "X-CabalSpy-Key": "your_key" }
    }
  }
}
```

## Built for depth

CabalSpy does not return samples. A 30-day wallet report covers every token the wallet touched, every
trade, and the full PnL curve — routinely tens of thousands of data points. That depth is why trading
terminals run on this data.

A language model works within a context window, so this server delivers that depth in a shape a model
can actually reason about. Every summary block comes through complete: period stats, win-rate
distribution, holder counts, PnL totals, profiles. Long detail lists are shortened, and the response
states exactly how many entries were left out, so a model never mistakes an excerpt for the whole
picture.

Responses that already fit are returned untouched.

Need every row? That is what the [SDKs](#also-available-as-an-sdk) and the REST API are for. Nothing
is lost here, it is one call away.

## Data notes the model is given

A model that guesses about data semantics will state something confidently wrong. So the tool
descriptions spell out how to read the numbers:

- **Market cap and unrealized PnL are Solana-native.** The other four chains report realized PnL,
  invested amounts, holdings and counters; market cap is not part of their dataset.
- **`realized_pnl` is sales minus purchases.** A wallet that has bought and not yet sold therefore
  shows its open position as negative. `still_holding` tells the two apart.
- **`lookup_wallet` searches every chain.** EVM addresses are identical across chains, so a wallet
  tracked on several returns the first match; pass a chain to the other tools when you need a
  specific one.
- **Bundle detection is Solana-native**, because it reads Jito bundles.

## Security

The key is read from the `X-CabalSpy-Key` header where the client can send one, and from an
`api_key` query parameter where it cannot. It is then forwarded to the CabalSpy API as an
`Authorization: Bearer` header, never as a query parameter.

The query parameter path is a deliberate compromise: claude.ai's web connector offers no way to
set a header and expects OAuth, so without it the server is unusable there. The cost is that the
key appears in the reverse proxy's access log. Keep those logs short, and prefer the header in
every client that supports one.

The key is never accepted as a tool argument, so a model can neither see it nor write it into a
transcript. Every tool is annotated `readOnlyHint`; nothing in the CabalSpy API can modify state.

Every tool is annotated `readOnlyHint`. Nothing in the CabalSpy API can modify state.

## Self-hosting

`mcp.cabalspy.xyz` runs the code in this repository. To run your own instance instead:

```bash
docker build -t cabalspy-mcp .
docker run -p 8081:8081 cabalspy-mcp
```

Configuration and deployment are covered in [DEPLOYMENT.md](DEPLOYMENT.md).

## Contributing

```bash
pip install -r requirements.txt
python3 test_server.py
```

The suite starts a mock API and exercises every tool, the auth paths, the client-side guards, the
error translation and the response shaping. It needs no API key and no network.

## FAQ

### What is a KOL wallet?

KOL stands for Key Opinion Leader: a trader or crypto personality whose token calls move markets. CabalSpy tracks their onchain wallets with a public identity attached — name, avatar, Twitter and Telegram handle — so a call can be checked against what the wallet actually did.

### How is smart money different from a KOL?

A KOL is identified by influence, a smart money wallet by track record. KOL trades carry social signal, smart money trades carry statistical signal. Both are wallet types on the same tools, so you can ask for either or merge them.

### What does bundle detection do?

On Solana, KOL wallets often buy through Jito bundles together with side wallets they control, which hides the true size of their position. `detect_bundles` groups those wallets, reports a confidence score and exposes the evidence: matching fees, block index, adjacency to the KOL transaction.

### Does it stream live data?

No, and it should not. MCP is request and response; a model cannot read a feed while it is answering. `get_recent_trades` and `get_activity_metrics` give you the current picture as a snapshot. For a genuine live stream, use the [WebSocket gateway](https://docs.cabalspy.xyz) with one of the SDKs.

### Do I need an API key?

Yes, your own. A free test key with 1000 requests is at [apidashboard.cabalspy.xyz](https://apidashboard.cabalspy.xyz/). Call `get_started` from inside your assistant and it will hand you the links.

## Also available as an SDK

If you are writing code rather than asking questions, the same API is available as [`cabalspy` on npm](https://www.npmjs.com/package/cabalspy), [PyPI](https://pypi.org/project/cabalspy/) and [crates.io](https://crates.io/crates/cabalspy), including the WebSocket streams this server deliberately does not expose.

## Repository

| File | Purpose |
|---|---|
| `cabalspy_mcp.py` | the server |
| `test_server.py` | offline test suite, no key or network needed |
| `server.json` | MCP registry entry |
| `glama.json` | Glama directory listing |
| `smithery-config-schema.json` | config schema shown to Smithery users |
| `Dockerfile` | self-hosting and directory sandboxes |
| `cabalspy-mcp.service` | hardened systemd unit |
| `DEPLOYMENT.md` | operations, for self-hosters |


## License

MIT
