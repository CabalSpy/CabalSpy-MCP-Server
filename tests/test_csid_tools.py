"""Offline tests for the CabalSpy ID (csid_*) tools and the shared HTTP layer.

Every HTTP call goes to an httpx.MockTransport, so the tests need no network and
no API key. Run:  pip install -r requirements.txt pytest && pytest -q
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import MCP_server as srv  # noqa: E402

CSID_TOOLS = {
    "csid_profile", "csid_wallet_owner", "csid_kols", "csid_token_theses",
    "csid_latest_theses", "csid_user_theses", "csid_thesis", "csid_leaderboard",
    "csid_platform_user", "csid_platform_leaderboard", "csid_competitions",
    "csid_callouts", "csid_callout_leaderboard", "csid_callout_stats",
}
BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

SANDBOX_PROFILE = {
    "avatar_url": None, "bio": "Test identity", "csid_id": "e2389a4d-4b23-4e79-b4a2-a5b8825bce5a",
    "joined_at": "2026-10-09T13:24:46Z", "kol": {"badge": True, "since": "2026-10-09T13:24:46Z"},
    "location": None, "name": "Sandbox KOL", "onchain": {"buys": 40, "sells": 37, "volume_7d_usd": 142000.0},
    "profile_url": None, "sandbox": True, "telegram": None, "username": "csid_sandbox_kol",
    "wallets": [{"address": "SBXkoL1111111111111111111111111111111111111",
                 "chains": [{"id": "solana", "name": "Solana"}], "family": "solana",
                 "verified_at": "2026-10-09T13:24:46Z"}],
    "website": None,
    "x": {"created_at": "2022-08-31T13:24:46Z", "followers": 48200, "following": 312, "id": "sandbox-1",
          "url": "https://x.com/csid_sandbox_kol", "username": "csid_sandbox_kol", "verified": False},
}
DEMO_BLOCK = {"notice": "Public demo", "remaining_today": 19}


def thesis(i: int, stance: str | None = "bull", private: bool = False) -> dict:
    return {
        "id": f"00000000-0000-0000-0000-00000000000{i}", "chain": "solana", "mint": BONK, "kind": "thesis",
        "parent_id": None, "body": f"thesis {i}", "stance": stance,
        "author": {"csid_id": "9e09e3e9-b360-4cbc-9fb4-3b6299e07331", "username": "alice", "name": "Alice",
                   "image_url": "https://pbs.twimg.com/x.jpg", "kol_badge": True,
                   "profile_url": "https://id.cabalspy.xyz/u/alice"},
        "likes": 3, "replies": 1, "reactions": {"like": 3},
        "reacted_by": [{"emoji": "like", "csid_id": "x", "username": "bob", "at": "2026-10-14T06:58:20Z"}],
        "my_reactions": [], "via": "CabalSpy Terminal", "created_at": "2026-10-14T06:56:16Z", "is_mine": False,
        "latest_replies": [{"id": "r1", "body": "agree", "author": {"username": "bob"},
                            "created_at": "2026-10-14T07:00:00Z", "kind": "reply"}],
        "position": {"private": True} if private else {
            "at_post": {"invested_usd": 100.0, "tokens_held": 1000.0, "first_buy": None},
            "now": {"invested_usd": 100.0, "realized_usd": 0.0, "holding_value_usd": 150.0,
                    "pnl_usd": 50.0, "pnl_percent": 50.0, "tokens_held": 1000.0, "status": "holding"}},
    }


class Mock:
    """Records requests and answers from a route table keyed by (host, path)."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.url.host, request.url.path)
        status, body = self.routes.get(key, (404, {"success": False, "error": {"code": "nope", "message": "no route"}}))
        return httpx.Response(status, json=body)

    def last(self) -> httpx.Request:
        return self.requests[-1]


@pytest.fixture
def mock(monkeypatch):
    m = Mock({})
    monkeypatch.setattr(srv, "_TRANSPORT", httpx.MockTransport(m))
    monkeypatch.setattr(srv, "API_BASE", "https://api.test")
    monkeypatch.setattr(srv, "CSID_API_BASE", "https://csid.test")
    monkeypatch.setattr(srv, "ENV_KEY", "")
    return m


@pytest.fixture
def own_key(monkeypatch):
    monkeypatch.setattr(srv, "ENV_KEY", "user-test-key")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def call(tool: str, **kwargs) -> dict:
    result = run(srv.mcp.call_tool(tool, kwargs))
    if isinstance(result, tuple):
        blocks, structured = result[0], result[1] if len(result) > 1 else None
        if isinstance(structured, dict):
            return structured.get("result", structured)
    else:
        blocks = result
    return json.loads("".join(getattr(b, "text", "") for b in blocks))


def ok(data, **extra) -> tuple[int, dict]:
    return 200, {"success": True, "data": data, **extra}


def fail(status: int, code: str, message: str = "msg") -> tuple[int, dict]:
    return status, {"success": False, "error": {"code": code, "message": message}}


# ── catalogue ─────────────────────────────────────────────────────────────────


def test_catalogue():
    tools = run(srv.mcp.list_tools())
    names = {t.name for t in tools}
    assert CSID_TOOLS <= names
    assert "get_token_stats" in names and "lookup_wallet" in names
    for t in tools:
        if t.name in CSID_TOOLS:
            assert len(t.description or "") > 150, t.name
            assert t.annotations and t.annotations.readOnlyHint, t.name
            for pname, p in (t.inputSchema or {}).get("properties", {}).items():
                assert p.get("description"), f"{t.name}.{pname} has no description"


def test_no_write_tools():
    names = {t.name for t in run(srv.mcp.list_tools())}
    assert not any(w in n for n in names for w in ("post", "create", "delete", "react", "report"))


# ── identity (CabalSpy API, demo = sandbox) ───────────────────────────────────


def test_profile_demo_is_slim_and_marked(mock):
    mock.routes[("api.test", "/v1/csid/profile")] = ok(SANDBOX_PROFILE, demo=DEMO_BLOCK)
    out = call("csid_profile", username="@csid_sandbox_kol")
    req = mock.last()
    assert req.url.params["username"] == "csid_sandbox_kol"
    assert req.headers["authorization"] == "Bearer demo"
    assert out["sandbox"] is True and "sandbox_note" in out and out["demo"] == DEMO_BLOCK
    assert out["kol_badge"] is True and out["x"]["followers"] == 48200
    assert out["wallets"] == [{"address": "SBXkoL1111111111111111111111111111111111111", "chains": ["solana"],
                               "verified_at": "2026-10-09T13:24:46Z"}]
    assert "avatar_url" not in out and "profile_url" not in out  # sandbox has no public page


def test_profile_needs_exactly_one_identifier(mock):
    out = call("csid_profile", username="a", csid_id="b")
    assert out["error"] == "invalid_parameter"
    out = call("csid_profile")
    assert out["error"] == "invalid_parameter"
    assert mock.requests == []


def test_profile_not_found_passes_csid_error(mock):
    mock.routes[("api.test", "/v1/csid/profile")] = fail(404, "profile_not_found", "No CabalSpy ID for @x.")
    out = call("csid_profile", x_id="123")
    assert out["error"] == "profile_not_found" and "lookup_wallet" in out["hint"]
    assert mock.last().url.params["x_id"] == "123"


def test_profile_by_address_and_unverified_wallet(mock):
    mock.routes[("api.test", "/v1/csid/wallet")] = fail(404, "wallet_not_found")
    out = call("csid_profile", address="So11111111111111111111111111111111111111112")
    assert out["verified"] is False and "error" not in out


def test_wallet_owner_single(mock):
    mock.routes[("api.test", "/v1/csid/wallet")] = ok({
        "address": "SBX", "chains": [{"id": "solana", "name": "Solana"}], "owner": SANDBOX_PROFILE,
        "verified_at": "2026-10-09T13:24:46Z"}, demo=DEMO_BLOCK)
    out = call("csid_wallet_owner", addresses="SBX")
    assert out["verified"] is True and out["chains"] == ["solana"]
    assert out["owner"]["username"] == "csid_sandbox_kol" and "bio" not in out["owner"]


def test_wallet_owner_batch(mock):
    mock.routes[("api.test", "/v1/csid/wallets/lookup")] = ok({"count": 2, "verified": 1, "results": [
        {"address": "0xabc", "error": "invalid_address", "verified": False},
        {"address": "SBX", "verified": True, "wallet": {"chains": [{"id": "solana"}], "owner": SANDBOX_PROFILE}},
    ]})
    out = call("csid_wallet_owner", addresses="0xabc, SBX")
    req = mock.last()
    assert req.method == "POST" and json.loads(req.content) == {"addresses": ["0xabc", "SBX"]}
    assert out["results"][0]["verified"] is True  # verified first
    assert out["results"][1] == {"address": "0xabc", "verified": False, "error": "invalid_address"}


def test_wallet_owner_limits(mock):
    assert call("csid_wallet_owner", addresses=",".join(["a"] * 101))["error"] == "invalid_parameter"
    assert call("csid_wallet_owner", addresses=" , ")["error"] == "missing_parameter"
    assert mock.requests == []


def test_kols(mock):
    mock.routes[("api.test", "/v1/csid/kols")] = ok({"count": 1, "kols": [SANDBOX_PROFILE], "next_cursor": "abc"})
    out = call("csid_kols", chain="base", limit=5)
    assert mock.last().url.params["chain"] == "base" and mock.last().url.params["limit"] == "5"
    assert out["count"] == 1 and out["next_cursor"] == "abc" and out["kols"][0]["kol_badge"] is True
    assert call("csid_kols", chain="doge")["error"] == "invalid_parameter"


# ── theses (CSID Data API, own key only) ──────────────────────────────────────


def test_theses_tools_refuse_demo_without_calling(mock):
    for tool, args in [("csid_token_theses", {"blockchain": "solana", "mint": BONK}),
                       ("csid_latest_theses", {}), ("csid_user_theses", {"username": "alice"}),
                       ("csid_thesis", {"thesis_id": "x"}), ("csid_leaderboard", {"blockchain": "solana"})]:
        out = call(tool, **args)
        assert out["error"] == "csid_setup_required", tool
        assert out["setup_url"] == srv.CSID_SETUP_URL
    assert mock.requests == []


def test_token_theses(mock, own_key):
    mock.routes[("csid.test", "/v1/theses/summary")] = ok({
        "theses": 3, "bull": 2, "bear": 1, "authors": 2,
        "token": {"chain": "solana", "mint": BONK, "name": "Bonk", "symbol": "BONK", "logo": "x", "price_usd": 0.00002}})
    mock.routes[("csid.test", "/v1/theses")] = ok([thesis(1), thesis(2, "bear", private=True)],
                                                  pagination={"next_cursor": "new:2"})
    out = call("csid_token_theses", blockchain="solana", mint=BONK, stance="bull", sort="top", limit=2,
               instance="csid_abc")
    summary_req, list_req = mock.requests
    assert summary_req.headers["authorization"] == "Bearer user-test-key"
    assert "x-real-ip" not in summary_req.headers
    assert list_req.url.params["stance"] == "bull" and list_req.url.params["sort"] == "top"
    assert list_req.url.params["instance"] == "csid_abc" and list_req.url.params["scope"] == "global"
    assert out["summary"] == {"theses": 3, "authors": 2, "bull": 2, "bear": 1, "bull_percent": 66.7}
    assert out["token"] == {"symbol": "BONK", "name": "Bonk", "price_usd": 0.00002}
    assert out["next_cursor"] == "new:2" and out["trade_url"].endswith(BONK)
    t1, t2 = out["theses"]
    assert t1["position"] == {"status": "holding", "tokens_held": 1000.0, "tokens_held_at_post": 1000.0,
                              "invested_usd": 100.0, "realized_usd": 0.0, "holding_value_usd": 150.0, "pnl_usd": 50.0,
                              "pnl_percent": 50.0}
    assert t2["position"]["private"] is True
    assert t1["author"] == {"username": "alice", "name": "Alice", "kol_badge": True,
                            "csid_id": "9e09e3e9-b360-4cbc-9fb4-3b6299e07331"}
    text = json.dumps(out)
    assert "reacted_by" not in text and "image_url" not in text and "my_reactions" not in text


def test_token_theses_next_page_skips_summary(mock, own_key):
    mock.routes[("csid.test", "/v1/theses")] = ok([], pagination={"next_cursor": None})
    out = call("csid_token_theses", blockchain="solana", mint=BONK, cursor="new:10")
    assert [r.url.path for r in mock.requests] == ["/v1/theses"]
    assert out["theses"] == [] and "summary" not in out


def test_token_theses_validation(mock, own_key):
    assert call("csid_token_theses", blockchain="sol", mint=BONK)["parameter"] == "blockchain"
    assert call("csid_token_theses", blockchain="solana", mint=BONK, stance="moon")["parameter"] == "stance"
    assert call("csid_token_theses", blockchain="solana", mint=BONK, sort="old")["parameter"] == "sort"
    assert mock.requests == []


@pytest.mark.parametrize("status,code", [(403, "no_instance"), (403, "product_not_enabled"),
                                         (400, "instance_required"), (404, "instance_not_found")])
def test_setup_errors_point_to_dashboard(mock, own_key, status, code):
    mock.routes[("csid.test", "/v1/theses/latest")] = fail(status, code, "Create a CabalSpy ID instance first")
    out = call("csid_latest_theses")
    assert out["error"] == code and out["setup_url"] == srv.CSID_SETUP_URL and "hint" in out


def test_invalid_key_on_data_api(mock, own_key):
    mock.routes[("csid.test", "/v1/theses/latest")] = fail(401, "invalid_api_key")
    assert call("csid_latest_theses")["error"] == "auth_failed"


def test_invalid_key_on_main_api_keeps_auth_answer(mock, own_key):
    mock.routes[("api.test", "/v1/csid/profile")] = fail(403, "invalid_api_key")
    assert call("csid_profile", username="alice")["error"] == "auth_failed"
    mock.routes[("api.test", "/v1/csid/profile")] = fail(403, "insufficient_credits")
    assert call("csid_profile", username="alice")["error"] == "insufficient_credits"


def test_latest_and_user_theses(mock, own_key):
    mock.routes[("csid.test", "/v1/theses/latest")] = ok([thesis(1)], pagination={"next_cursor": "20"})
    out = call("csid_latest_theses", blockchain="base", users="instance")
    assert mock.last().url.params["users"] == "instance"
    assert out["theses"][0]["mint"] == BONK and out["next_cursor"] == "20"
    mock.routes[("csid.test", "/v1/theses/user")] = ok([thesis(1)])
    out = call("csid_user_theses", username="@alice")
    assert mock.last().url.params["username"] == "alice" and "csid_id" not in mock.last().url.params
    assert "next_cursor" not in out
    assert call("csid_user_theses")["error"] == "invalid_parameter"


def test_thesis_with_replies(mock, own_key):
    mock.routes[("csid.test", "/v1/theses/item")] = ok(thesis(1))
    mock.routes[("csid.test", "/v1/theses/replies")] = ok(
        [{"id": "r1", "body": "agree", "author": {"username": "bob", "image_url": "x"}, "likes": 0,
          "created_at": "2026-10-14T07:00:00Z"}], pagination={"next_cursor": "50"})
    out = call("csid_thesis", thesis_id="00000000-0000-0000-0000-000000000001")
    assert out["thesis"]["body"] == "thesis 1" and "latest_replies" not in out["thesis"]
    assert out["replies"] == [{"id": "r1", "author": {"username": "bob"}, "body": "agree",
                               "created_at": "2026-10-14T07:00:00Z"}]
    assert out["next_cursor"] == "50" and out["trade_url"].endswith(BONK)


def test_thesis_not_found(mock, own_key):
    mock.routes[("csid.test", "/v1/theses/item")] = fail(404, "not_found", "This post is not available.")
    out = call("csid_thesis", thesis_id="nope")
    assert out == {"error": "not_found", "message": "This post is not available."}


def test_leaderboard(mock, own_key):
    mock.routes[("csid.test", "/v1/wallets/leaderboard")] = ok({
        "blockchain": "solana", "scope": "instance", "period": "7d", "sort": "pnl_usd", "currency": "SOL",
        "pagination": {"total": 1, "next_cursor": None},
        "leaderboard": [{"rank": 1, "wallet": "W1", "profile": {"username": "alice", "csid_id": "c1", "kol": False,
                                                                 "image_url": "x"},
                         "period_stats": {"total_volume": 2.5, "total_volume_usd": 400.0, "realized_pnl": 0.5,
                                          "realized_pnl_usd": 80.0, "realized_pnl_percentage": 20.0, "total_txn": 6},
                         "period_win_rate_distribution": {"win_rate_percentage": 50.0, "closed_count": 2},
                         "period_history_tokens": {"total_tokens": 3}}]})
    out = call("csid_leaderboard", blockchain="solana", sort="pnl_usd")
    assert mock.last().url.params["scope"] == "instance"
    assert out["leaderboard"][0] == {"rank": 1, "wallet": "W1", "username": "alice", "csid_id": "c1",
                                     "volume": 2.5, "volume_usd": 400.0, "realized_pnl": 0.5,
                                     "realized_pnl_usd": 80.0, "realized_pnl_percent": 20.0,
                                     "win_rate_percent": 50.0, "closed_positions": 2, "trades": 6, "tokens": 3}
    assert out["total"] == 1 and "next_cursor" not in out


def test_leaderboard_global_needs_enterprise(mock, own_key):
    mock.routes[("csid.test", "/v1/wallets/leaderboard")] = fail(
        403, "scope_not_allowed", "scope=global is available on the Enterprise plan.")
    out = call("csid_leaderboard", blockchain="solana", scope="global")
    assert out["error"] == "scope_not_allowed" and "Enterprise" in out["message"]
    assert call("csid_leaderboard", blockchain="solana", sort="moon")["parameter"] == "sort"


# ── white-label ───────────────────────────────────────────────────────────────

SOL_WALLET = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"


def entry(rank: int, ext: str, pnl: float) -> dict:
    return {"rank": rank, "external_id": ext, "wallet": SOL_WALLET, "verified": False,
            "profile": {"profile_url": None},
            "period_stats": {"total_volume": 10.0, "total_volume_usd": 1500.0, "realized_pnl": 1.0,
                             "realized_pnl_usd": pnl, "total_txn": 7},
            "period_win_rate_distribution": {"win_rate_percentage": 50.0, "closed_count": 4}}


def test_white_label_tools_refuse_demo_without_calling(mock):
    assert call("csid_platform_user", external_id="42")["error"] == "csid_setup_required"
    assert call("csid_platform_leaderboard", blockchain="solana")["error"] == "csid_setup_required"
    assert call("csid_competitions")["error"] == "csid_setup_required"
    assert mock.requests == []


def test_platform_user(mock, own_key):
    mock.routes[("csid.test", "/v1/platform-users/profile")] = ok({
        "csid_id": "c1", "external_id": "did:privy:abc", "display_name": "Trader 1", "claimed": False,
        "x": None, "telegram": None, "kol": {"badge": False, "since": None},
        "wallets": [{"address": SOL_WALLET, "family": "solana", "status": "active", "source": "privy"}],
        "period": "7d", "recent_trades": [], "theses": {"total": 0, "latest": []},
        "trading": [{"blockchain": "solana", "currency": "SOL", "total_volume": 10.0,
                     "total_volume_usd": 1500.0, "realized_pnl_usd": 120.0, "win_rate_percentage": 50.0,
                     "closed_count": 4, "total_txn": 7, "tokens": 3,
                     "wallets": [{"address": SOL_WALLET, "verified": False, "total_volume_usd": 1500.0,
                                  "realized_pnl_usd": 120.0}]}],
        "created_at": "2026-10-26T10:00:00Z"})
    out = call("csid_platform_user", external_id=" did:privy:abc ", period="30d")
    params = mock.last().url.params
    assert params["external_id"] == "did:privy:abc" and params["period"] == "30d"
    assert out["display_name"] == "Trader 1" and out["wallets"][0]["status"] == "active"
    assert out["trading"][0]["realized_pnl_usd"] == 120.0 and "kol" not in out
    assert call("csid_platform_user", external_id=" ")["parameter"] == "external_id"
    assert call("csid_platform_user", external_id="42", period="1y")["parameter"] == "period"


def test_platform_user_not_found_passes_error(mock, own_key):
    mock.routes[("csid.test", "/v1/platform-users/profile")] = fail(
        404, "platform_user_not_found", "No user with this external_id in your instance.")
    assert call("csid_platform_user", external_id="nobody")["error"] == "platform_user_not_found"


def test_platform_leaderboard(mock, own_key):
    mock.routes[("csid.test", "/v1/platform-users/leaderboard")] = ok(
        {"blockchain": "solana", "period": "7d", "sort": "pnl_usd", "currency": "SOL", "trust": "all",
         "leaderboard": [entry(1, "u1", 300.0), entry(2, "u2", 100.0)]},
        pagination={"limit": 2, "total": 9, "has_more": True, "next_cursor": SOL_WALLET})
    out = call("csid_platform_leaderboard", blockchain="solana", limit=2, verified_only=True)
    params = mock.last().url.params
    assert params["trust"] == "verified" and params["limit"] == "2" and "cursor" not in params
    assert [r["external_id"] for r in out["leaderboard"]] == ["u1", "u2"]
    assert out["total"] == 9 and out["next_cursor"] == SOL_WALLET
    call("csid_platform_leaderboard", blockchain="solana")
    assert "trust" not in mock.last().url.params
    assert call("csid_platform_leaderboard", blockchain="sol")["parameter"] == "blockchain"


def test_platform_leaderboard_empty_has_note(mock, own_key):
    mock.routes[("csid.test", "/v1/platform-users/leaderboard")] = ok(
        {"blockchain": "base", "leaderboard": []}, pagination={"total": 0, "next_cursor": None})
    out = call("csid_platform_leaderboard", blockchain="base")
    assert out["leaderboard"] == [] and "note" in out and "next_cursor" not in out


def test_competitions_list_and_detail(mock, own_key):
    comp = {"id": "k1", "name": "Weekly", "chain": "solana", "metric": "pnl_usd", "status": "running",
            "starts_at": "2026-10-27T00:00:00Z", "ends_at": "2026-11-03T00:00:00Z", "participants": 120,
            "min_trades": 1, "min_volume_usd": 0.0, "wallet_trust": "all", "enrollment": "opt_in",
            "late_join": True, "prizes": None, "rules_version": 2, "description": "Top PnL wins"}
    mock.routes[("csid.test", "/v1/competitions")] = ok([comp], pagination={"total": 1})
    out = call("csid_competitions", status="running")
    assert mock.last().url.params["status"] == "running"
    assert out["total"] == 1 and out["competitions"][0]["name"] == "Weekly"
    assert "description" not in out["competitions"][0]

    mock.routes[("csid.test", "/v1/competitions/detail")] = ok(
        {**comp, "changes": [{"rules_version": 2, "during": "running", "changes": {"min_trades": [0, 1]},
                              "note": "spam", "changed_at": "2026-10-28T10:00:00Z"}],
         "changed_while_running": True})
    mock.routes[("csid.test", "/v1/competitions/standings")] = ok(
        {"competition_id": "k1", "status": "running", "metric": "pnl_usd", "rules_version": 2,
         "updated_at": "2026-10-28T16:50:00Z", "final": False,
         "standings": [{"rank": 1, "ranked": True, "external_id": "u1", "csid_id": "c1", "score": 300.0}]})
    out = call("csid_competitions", competition_id="k1", limit=5)
    assert mock.last().url.params["id"] == "k1" and mock.last().url.params["limit"] == "5"
    assert out["changed_while_running"] is True and out["changes"][0]["note"] == "spam"
    assert out["standings"][0]["external_id"] == "u1" and out["final"] is False


def test_competitions_empty_and_validation(mock, own_key):
    mock.routes[("csid.test", "/v1/competitions")] = ok([], pagination={"total": 0})
    assert "white-label" in call("csid_competitions")["note"]
    assert call("csid_competitions", status="live")["parameter"] == "status"
    mock.routes[("csid.test", "/v1/competitions/detail")] = fail(404, "competition_not_found")
    assert call("csid_competitions", competition_id="nope")["error"] == "competition_not_found"


# ── callouts (an extra, switched on per instance) ─────────────────────────────

AUTHOR = {"csid_id": "c1", "external_id": "u1", "name": "Trader 1", "username": "trader1",
          "avatar_url": None, "kol": False}


def callout(i: int, phase: str = "first_day") -> dict:
    """The shape of app/callouts.py present()."""
    return {
        "id": f"co{i}", "chain": "solana", "mint": BONK,
        "token": {"name": "Bonk", "symbol": "BONK", "logo": "https://x/logo.png"},
        "author": AUTHOR, "note": "send it", "called_at": "2026-10-30T12:00:00Z",
        "window_ends_at": "2026-10-31T12:00:00Z", "status": "tracking" if phase != "stopped" else "final",
        "at_call": {"price_usd": 0.00002, "market_cap_usd": 1_500_000.0},
        "now": {"price_usd": 0.00003, "market_cap_usd": 2_250_000.0, "x": 1.5, "at": "2026-10-30T13:00:00Z"},
        "peak": {"price_usd": 0.00005, "market_cap_usd": 3_750_000.0, "x": 2.5, "at": "2026-10-30T12:40:00Z"},
        "score_x": 2.5, "source": "api",
        "tracking": {"active": phase != "stopped", "phase": phase, "next_check_at": None, "below_10k_since": None,
                     "daily_checks": 0, "stopped_at": None, "stop_reason": None if phase != "stopped" else "below_10k"},
    }


SUMMARY = {"callouts": 4, "avg_peak_x": 2.1, "median_peak_x": 1.8, "best_peak_x": 4.0, "sum_peak_x": 8.4,
           "hits": 2, "hit_rate": 50.0}


def test_callout_tools_refuse_demo_without_calling(mock):
    assert call("csid_callouts")["error"] == "csid_setup_required"
    assert call("csid_callout_leaderboard")["error"] == "csid_setup_required"
    assert call("csid_callout_stats", external_id="u1")["error"] == "csid_setup_required"
    assert mock.requests == []


def test_callouts_latest_slim(mock, own_key):
    mock.routes[("csid.test", "/v1/callouts")] = ok(
        [callout(1), callout(2, "stopped")], pagination={"limit": 2, "has_more": True, "next_cursor": "abc"})
    out = call("csid_callouts", limit=2)
    params = mock.last().url.params
    assert params["limit"] == "2" and "chain" not in params and "external_id" not in params
    first = out["callouts"][0]
    assert first == {
        "id": "co1", "chain": "solana", "mint": BONK, "token": "BONK",
        "author": {"external_id": "u1", "username": "trader1", "name": "Trader 1", "csid_id": "c1"},
        "called_at": "2026-10-30T12:00:00Z", "market_cap_at_call_usd": 1_500_000.0, "price_at_call_usd": 0.00002,
        "now_x": 1.5, "now_market_cap_usd": 2_250_000.0, "peak_x": 2.5, "peak_at": "2026-10-30T12:40:00Z",
        "score_x": 2.5, "phase": "first_day", "note": "send it"}
    assert out["callouts"][1]["phase"] == "stopped" and out["callouts"][1]["stop_reason"] == "below_10k"
    assert out["next_cursor"] == "abc" and "trade_url" not in out


def test_callouts_for_token_and_user(mock, own_key):
    mock.routes[("csid.test", "/v1/callouts")] = ok([callout(1)], pagination={"next_cursor": None})
    out = call("csid_callouts", chain="Solana", mint=f" {BONK} ")
    params = mock.last().url.params
    assert params["chain"] == "solana" and params["mint"] == BONK
    assert out["trade_url"].endswith(BONK) and "next_cursor" not in out
    call("csid_callouts", external_id=" u1 ", cursor="abc", instance="csid_x")
    params = mock.last().url.params
    assert params["external_id"] == "u1" and params["cursor"] == "abc" and params["instance"] == "csid_x"
    call("csid_callouts", csid_id="c1")
    assert mock.last().url.params["csid_id"] == "c1"


def test_callouts_validation(mock, own_key):
    assert call("csid_callouts", mint=BONK)["parameter"] == "chain"
    assert call("csid_callouts", chain="sol")["parameter"] == "chain"
    assert call("csid_callouts", external_id="u1", csid_id="c1")["parameter"] == "external_id"
    assert mock.requests == []


def test_callouts_empty_has_note(mock, own_key):
    mock.routes[("csid.test", "/v1/callouts")] = ok([], pagination={"next_cursor": None})
    out = call("csid_callouts", external_id="nobody-yet")
    assert out["callouts"] == [] and "note" in out


def test_callout_leaderboard(mock, own_key):
    entry_ = {**SUMMARY, "rank": 1, "csid_id": "c1", "author": AUTHOR,
              "best_call": {"id": "co1", "chain": "solana", "mint": BONK, "symbol": "BONK", "peak_x": 4.0}}
    mock.routes[("csid.test", "/v1/callouts/leaderboard")] = ok(
        {"period": "30d", "chain": None, "sort": "hit_rate", "hit_x": 3.0, "leaderboard": [entry_]},
        pagination={"limit": 1, "total": 7, "has_more": True, "next_cursor": "o1"})
    out = call("csid_callout_leaderboard", period="30d", sort="hit_rate", min_callouts=3, hit_x=3, limit=1)
    params = mock.last().url.params
    assert params["period"] == "30d" and params["sort"] == "hit_rate" and params["min_callouts"] == "3"
    assert float(params["hit_x"]) == 3.0 and params["limit"] == "1" and "chain" not in params
    row = out["leaderboard"][0]
    assert row["rank"] == 1 and row["external_id"] == "u1" and row["hit_rate_percent"] == 50.0
    assert "hit_rate" not in row and row["best_call"] == {"token": "BONK", "chain": "solana", "mint": BONK,
                                                          "peak_x": 4.0}
    assert out["chain"] == "all" and out["total"] == 7 and out["next_cursor"] == "o1"
    call("csid_callout_leaderboard", chain="base")
    assert mock.last().url.params["chain"] == "base" and mock.last().url.params["period"] == "7d"


def test_callout_leaderboard_validation_and_empty(mock, own_key):
    assert call("csid_callout_leaderboard", period="1y")["parameter"] == "period"
    assert call("csid_callout_leaderboard", sort="pnl_usd")["parameter"] == "sort"
    assert call("csid_callout_leaderboard", chain="sol")["parameter"] == "chain"
    assert mock.requests == []
    mock.routes[("csid.test", "/v1/callouts/leaderboard")] = ok(
        {"period": "6h", "leaderboard": []}, pagination={"total": 0, "next_cursor": None})
    out = call("csid_callout_leaderboard", period="6h")
    assert out["leaderboard"] == [] and "note" in out and "next_cursor" not in out


def test_callout_stats(mock, own_key):
    periods = {p: {**SUMMARY, "avg_now_x": 1.2, "tracking": 1} for p in ("6h", "1d", "7d", "30d")}
    periods["6h"] = {"callouts": 0, "avg_peak_x": None, "median_peak_x": None, "best_peak_x": None,
                     "sum_peak_x": 0.0, "hits": 0, "hit_rate": 0.0, "avg_now_x": None, "tracking": 0}
    mock.routes[("csid.test", "/v1/callouts/stats")] = ok(
        {"user": AUTHOR, "hit_x": 2.0, "periods": periods, "callouts_all_time": 12})
    out = call("csid_callout_stats", external_id=" u1 ")
    params = mock.last().url.params
    assert params["external_id"] == "u1" and "csid_id" not in params
    assert out["user"]["external_id"] == "u1" and out["callouts_all_time"] == 12
    assert out["periods"]["7d"]["hit_rate_percent"] == 50.0 and out["periods"]["7d"]["avg_now_x"] == 1.2
    assert out["periods"]["6h"] == {"callouts": 0, "sum_peak_x": 0.0, "hits": 0, "hit_rate_percent": 0.0,
                                    "tracking": 0}
    call("csid_callout_stats", csid_id="c1", hit_x=5)
    assert mock.last().url.params["csid_id"] == "c1" and float(mock.last().url.params["hit_x"]) == 5.0


def test_callout_stats_validation(mock, own_key):
    assert call("csid_callout_stats")["parameter"] == "external_id"
    assert call("csid_callout_stats", external_id="u1", csid_id="c1")["parameter"] == "external_id"
    assert mock.requests == []
    mock.routes[("csid.test", "/v1/callouts/stats")] = fail(
        404, "platform_user_not_found", "No user with this external_id in your instance.")
    assert call("csid_callout_stats", external_id="nobody")["error"] == "platform_user_not_found"


@pytest.mark.parametrize("tool,path,args", [
    ("csid_callouts", "/v1/callouts", {}),
    ("csid_callout_leaderboard", "/v1/callouts/leaderboard", {}),
    ("csid_callout_stats", "/v1/callouts/stats", {"external_id": "u1"}),
])
def test_feature_not_enabled_passes_through(mock, own_key, tool, path, args):
    mock.routes[("csid.test", path)] = fail(
        403, "feature_not_enabled", "Callouts are not enabled for this instance. Contact CabalSpy to switch them on.")
    out = call(tool, **args)
    assert out["error"] == "feature_not_enabled" and "Callouts are not enabled" in out["message"]
    assert out["contact"] == "contact@cabalspy.xyz" and "on request" in out["hint"]
    assert "setup_url" not in out


def test_competitions_callout_kind(mock, own_key):
    comp = {"id": "k2", "name": "Best caller", "kind": "callouts", "chain": "all", "metric": "avg_peak_x",
            "status": "running", "starts_at": "2026-10-27T00:00:00Z", "ends_at": "2026-11-03T00:00:00Z",
            "participants": 30, "min_callouts": 3, "hit_x": 2.0, "wallet_trust": "all", "enrollment": "opt_in",
            "late_join": True, "prizes": None, "rules_version": 1}
    mock.routes[("csid.test", "/v1/competitions")] = ok([comp], pagination={"total": 1})
    item = call("csid_competitions")["competitions"][0]
    assert item["kind"] == "callouts" and item["min_callouts"] == 3 and item["hit_x"] == 2.0
    assert item["metric"] == "avg_peak_x" and "min_trades" not in item
    mock.routes[("csid.test", "/v1/competitions/detail")] = ok({**comp, "changes": [], "changed_while_running": False})
    mock.routes[("csid.test", "/v1/competitions/standings")] = ok(
        {"competition_id": "k2", "updated_at": "2026-10-28T16:50:00Z", "final": False,
         "standings": [{"rank": 1, "external_id": "u1", "score": 3.2,
                        "stats": {**SUMMARY, "best_call": {"symbol": "BONK", "peak_x": 4.0}}}]})
    out = call("csid_competitions", competition_id="k2")
    assert out["kind"] == "callouts" and out["min_callouts"] == 3 and out["hit_x"] == 2.0
    assert out["standings"][0]["stats"]["best_call"]["symbol"] == "BONK"


def test_competitions_trading_kind(mock, own_key):
    comp = {"id": "k1", "name": "Weekly", "kind": "trading", "metric": "pnl_usd", "min_trades": 1,
            "min_volume_usd": 0.0}
    mock.routes[("csid.test", "/v1/competitions")] = ok([comp], pagination={"total": 1})
    item = call("csid_competitions")["competitions"][0]
    assert item["kind"] == "trading" and item["min_trades"] == 1 and "min_callouts" not in item


# ── the refactored HTTP layer still behaves like before for the old tools ─────


def test_old_tool_errors_unchanged(mock):
    mock.routes[("api.test", "/v1/tokens/stats")] = fail(404, "token_not_found")
    out = call("get_token_stats", blockchain="solana", mint=BONK)
    assert out["error"] == "not_found" and "labeled wallets" in out["message"]
    mock.routes[("api.test", "/v1/wallets/lookup")] = fail(401, "invalid_api_key")
    assert call("lookup_wallet", address="abc")["error"] == "auth_failed"
    mock.routes[("api.test", "/v1/wallets/lookup")] = fail(429, "demo_limit_reached")
    assert call("lookup_wallet", address="abc")["error"] == "demo_limit_reached"
    mock.routes[("api.test", "/v1/wallets/lookup")] = fail(403, "insufficient_credits")
    assert call("lookup_wallet", address="abc")["error"] == "insufficient_credits"


def test_old_tool_success_with_demo_block(mock):
    mock.routes[("api.test", "/v1/wallets/lookup")] = ok({"name": "x"}, demo=DEMO_BLOCK)
    out = call("lookup_wallet", address="abc")
    assert out == {"name": "x", "demo": DEMO_BLOCK}
    assert mock.last().headers["user-agent"] == f"cabalspy-mcp/{srv.VERSION}"
