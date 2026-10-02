# Changelog

## 2.1.0 — 2026-10-02

- Token tools (`get_token_stats`, `get_token_holders`, `get_token_transactions`, `detect_bundles`) now return a `trade_url` for Solana tokens: the token page in the [CabalSpy Terminal](https://app.cabalspy.xyz/).
- `get_started` returns the website (`https://www.cabalspy.xyz/mcp/`) and the trading terminal.
- Fixed: `requirements.txt` now pins `mcp<2`. mcp 2.x renamed FastMCP, so a fresh install (including the Dockerfile) failed to start.
- Website and pricing links point to `www.cabalspy.xyz`.

## 2.0.0

- 21 read-only tools covering the full v1 API on Solana, Base, BNB Chain, Ethereum and Robinhood Chain.
