# Changelog

## 2.2.0 — 2026-10-07

- Works without a key. A caller with no `X-CabalSpy-Key` now runs on the public demo key instead of getting `missing_api_key`: 20 requests per IP per day, data delayed 15 minutes, at most 5 rows per list.
- Demo results include the API's `demo` block, and the server instructions tell the model to say the data is delayed.
- `demo_limit_reached` is returned as its own error with the link to a free test key, instead of a generic `rate_limited`.
- The caller's IP is forwarded as `X-Real-IP`, so each user has their own demo budget. For it to count, point `CABALSPY_API_BASE` at the API on the same machine (the API trusts the header only from localhost).
- `get_started` describes the demo, including the keyless REST and WebSocket endpoints on `demo-api.cabalspy.xyz`.
- New setting `CABALSPY_DEMO_KEY` (default `demo`).

## 2.1.0 — 2026-10-02

- Token tools (`get_token_stats`, `get_token_holders`, `get_token_transactions`, `detect_bundles`) now return a `trade_url` for Solana tokens: the token page in the [CabalSpy Terminal](https://app.cabalspy.xyz/).
- `get_started` returns the website (`https://www.cabalspy.xyz/mcp/`) and the trading terminal.
- Fixed: `requirements.txt` now pins `mcp<2`. mcp 2.x renamed FastMCP, so a fresh install (including the Dockerfile) failed to start.
- Website and pricing links point to `www.cabalspy.xyz`.

## 2.0.0

- 21 read-only tools covering the full v1 API on Solana, Base, BNB Chain, Ethereum and Robinhood Chain.
