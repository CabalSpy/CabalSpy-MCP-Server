# CabalSpy MCP server — KOL and smart money wallet tracking for AI assistants

Realtime **KOL API** and onchain wallet tracking for AI assistants. CabalSpy monitors labeled wallets — key opinion leaders (KOLs), smart money and whales — across **Solana, Base, BNB Chain, Ethereum and Robinhood Chain**, and exposes the data as Model Context Protocol tools.

Connect it to Claude, Cursor, or any MCP client and ask about onchain trading activity in plain language. No code, no SDK, no integration work.

**What people use it for:** vetting a KOL call before following it, checking whether a launch was bundled, finding which wallets accumulate together, building copy-trading shortlists, and answering "who is this address" in one line.

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

### Claude Desktop / claude.ai

Settings → Connectors → add a custom connector pointing to `https://mcp.cabalspy.xyz/mcp`, with the header `X-CabalSpy-Key: <your key>`.

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

## Responses are compacted on purpose

A 30-day wallet report from the API can carry more than 70,000 values. Handing that to a model costs a fortune, overruns the context window, and does not help it answer anything.

Responses that fit are returned untouched. Only when a payload would exceed the budget are lists shortened, and the payload then says so explicitly, which stops a model from assuming it saw the whole picture. In testing, a 411 KB payload became 14 KB with every summary field intact.

## What the model is told about

Some of the API's behaviour is surprising, so the tool descriptions and the server instructions state it outright rather than letting a model guess:

- **Market cap and unrealized PnL are Solana-only.** On the other four chains those fields are null by design.
- **`realized_pnl` is sales minus purchases.** A wallet still holding everything it bought reports its whole investment as a loss at -100 percent. `still_holding` disambiguates.
- **`lookup_wallet` can report the wrong chain.** The same EVM address may be tracked on several, and only the first match is returned.
- **Signals are not paginable.** The endpoint reports that more results exist but returns no usable cursor, so raise the limit instead.
- **Bundle detection is Solana-only**, since it depends on Jito bundles.

## Security

The API key is read from the `X-CabalSpy-Key` header and sent onward as an `Authorization: Bearer` header, never as a query parameter — query strings end up in access logs, proxy logs and browser history. It is never accepted as a tool argument, so a model can neither see it nor write it into a transcript.

Every tool is annotated `readOnlyHint`. Nothing in the CabalSpy API can modify state.

## Running it

```bash
pip install -r requirements.txt
MCP_PORT=8081 python3 cabalspy_mcp.py
```

Serves `http://0.0.0.0:8081/mcp`, with nginx terminating TLS in front.

| Variable | Purpose |
|---|---|
| `CABALSPY_API_BASE` | REST endpoint, default `https://api.cabalspy.xyz` |
| `CABALSPY_API_KEY` | fallback key for single-user or demo deployments |
| `MCP_HOST`, `MCP_PORT` | bind address, default `0.0.0.0:8081` |

## Tests

```bash
python3 test_server.py
```

Starts a mock API, calls every tool, and checks the catalogue, the auth path, the guards, the error translation and the compaction. No API key, no network.

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

## License

MIT
