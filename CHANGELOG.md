# Changelog

## 2.5.0 — 2026-10-31

- **White-label tools** for platforms that import their own users into a CabalSpy ID instance, all read-only:
  - `csid_platform_user` — one of your users by your own user id (`external_id`): wallets with trust status, X/Telegram/KOL badge, trading stats per chain for a period, latest trades and theses.
  - `csid_platform_leaderboard` — your platform's users ranked on one chain by `pnl_usd`, `pnl`, `volume`, `win_rate` or `trades`; `verified_only` narrows it to payment-verified wallets.
  - `csid_competitions` — your trading competitions (filter by status); with `competition_id` the rules, every rule change and the current standings.
- `get_started` and the server instructions describe white-label.

## 2.4.0 — 2026-10-26

- **Calls:** `get_calls` returns the curated CabalSpy calls (the ones posted in Discord) with their trigger wallets and 24 h performance; `get_call_stats` the hit rates per chain and tier. This version ran on mcp.cabalspy.xyz before it reached this repository.

## 2.3.0 — 2026-10-15

- **CabalSpy ID (SocialFi) tools**, all read-only:
  - `csid_profile` — verified identity by X handle, CSID id, X id or wallet: X account, Telegram, KOL badge, verified wallets per chain, 7-day activity.
  - `csid_wallet_owner` — who proved ownership of 1 to 100 wallets, or `verified: false`.
  - `csid_kols` — KOLs with a reviewed CabalSpy ID badge, per chain.
  - `csid_token_theses` — bull/bear summary and theses for one token, each with the author's live position and PnL; `sort`, `stance`, `scope`, cursor.
  - `csid_latest_theses`, `csid_user_theses`, `csid_thesis` (with replies).
  - `csid_leaderboard` — your instance's verified traders ranked (every CabalSpy ID user on Enterprise).
- Identity tools work on the keyless demo with sandbox identities only. Theses and the leaderboard use the CabalSpy ID Data API (`api-id.cabalspy.xyz`, same key) and need a CabalSpy ID instance; without one they answer `csid_setup_required` / `no_instance` with the setup link.
- Optional `instance` argument, or `X-CSID-Instance` header / `csid_instance` query parameter, for accounts with several instances.
- Ethereum smart money: `eth` now accepts `smart` like the other EVM chains (already live since 2026-10-15).
- New setting `CSID_API_BASE`. User-Agent carries the server version.
- Dockerfile copies `MCP_server.py` (it referenced a file that is not in the repository).
- Offline tests in `tests/` (`pytest`).

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
