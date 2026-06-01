# CabalSpy MCP Server

**Real-time crypto wallet tracking for AI assistants.** CabalSpy monitors labeled wallets — key opinion leaders (KOLs), smart money and whales — across **Solana, BNB Chain, Base and Ethereum**, and exposes the data as Model Context Protocol (MCP) tools.

Connect it to Claude, Cursor, or any MCP client and ask about on-chain trading activity in plain language.

- **Remote endpoint:** `https://mcp.cabalspy.xyz/mcp`
- **Transport:** Streamable HTTP
- **Auth:** per-user API key via the `X-CabalSpy-Key` header
- **Free test key:** 1000 requests at [cabalspy.xyz/dashboard](https://cabalspy.xyz/dashboard)
- **Pricing:** [cabalspy.xyz/pricing](https://cabalspy.xyz/pricing)

## Tools

| Tool | What it does |
|------|--------------|
| `get_leaderboard` | Top wallets ranked by volume for a chain, wallet type and period (6h / 1d / 7d / 30d) |
| `get_wallet_tracker` | Realized PnL, win rate, volume, trade counts and active tokens for one wallet |
| `get_wallet_history` | Complete lifetime trading history, paginated, with per-token breakdown |
| `get_wallet_holdings` | Current on-chain token positions |
| `get_pnl_calendar` | Daily and monthly realized profit and loss |
| `get_wallet_connections` | Wallets that trade the same tokens as a given wallet |
| `list_wallets` | Browse all tracked wallets for a chain and type |
| `lookup_wallet` | Check whether an address is tracked, across all chains |
| `get_started` | Onboarding: how to get a free API key and connect |

## Questions it answers

- "Who are the best-performing Solana KOLs today?"
- "What is this wallet's lifetime PnL?"
- "Which whales are accumulating right now?"
- "Which wallets trade similar tokens to this address?"

## Connecting

### Claude Desktop / claude.ai

Add a custom connector (Settings → Connectors) pointing to:

```
https://mcp.cabalspy.xyz/mcp
```

### MCP client config (Cursor, VS Code, etc.)

```json
{
  "mcpServers": {
    "cabalspy": {
      "type": "http",
      "url": "https://mcp.cabalspy.xyz/mcp"
    }
  }
}
```

### Authentication

Every request needs your CabalSpy API key, sent as the `X-CabalSpy-Key` header.
Get a free test key (1000 requests, no cost) at
[cabalspy.xyz/dashboard](https://cabalspy.xyz/dashboard).

## Supported chains

Solana · BNB Chain · Base · Ethereum

## Wallet types

KOL · Smart money · Whale

## License

MIT
