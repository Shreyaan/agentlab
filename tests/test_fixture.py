import httpx
import psycopg
import pytest

from agentlab.environment import EnvironmentSpec, catalog
from agentlab.fixture import FixturePool
from agentlab.protocol import ToolFault
from agentlab.records import Row
from agentlab.scenario import load_suite

from .conftest import REFUND_ENV, ROOT, TRAVEL_ENV

SEED: dict[str, list[Row]] = {
    "customers": [{"id": "C-1", "name": "Ada"}],
    "orders": [{"id": "ORD-1", "customer_id": "C-1", "amount_cents": 500}],
    "settings": [{"key": "approval_limit_cents", "value": 1000}],
}
REFUND = {"order_id": "ORD-1", "amount_cents": 500}
TRAVEL_SEED: dict[str, list[Row]] = {
    "flights": [{"id": "FL-1", "origin": "SFO", "destination": "JFK", "seats_left": 1, "price_cents": 900}]
}
TIMEOUT = [ToolFault(tool="issue_refund", action="timeout_after_commit")]


def post(url: str, env: str, tool: str, body: dict | None = None, **headers: str) -> httpx.Response:
    return httpx.post(f"{url}/env/{env}/tools/{tool}", json=body or {}, headers=headers)


def test_ddl_comes_from_the_spec(envs: FixturePool) -> None:
    fx = envs.create("t_ddl", TRAVEL_ENV, TRAVEL_SEED)
    try:
        assert fx.state()["flights"][0]["seats_left"] == 1
        assert fx.query(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'payments' ORDER BY 1"
        ) == [("amount_cents",), ("booking_id",), ("id",)]
        assert fx.call("create_booking", {"flight_id": "FL-1", "passenger": "A"})[0] == 201
        assert fx.query(
            "SELECT count(*) FROM pg_constraint WHERE contype = 'f' AND connamespace = 'env_t_ddl'::regnamespace"
        ) == [(2,)]
    finally:
        envs.drop("t_ddl")


def test_seed_is_validated_against_the_spec(envs: FixturePool) -> None:
    with pytest.raises(ValueError, match="unknown table"):
        envs.create("t_seed1", REFUND_ENV, {"nope": [{"a": 1}]})
    with pytest.raises(ValueError, match="unknown orders column"):
        envs.create("t_seed2", REFUND_ENV, {"orders": [{"id": "O", "evil": 1}]})
    with pytest.raises(ValueError, match="invalid environment id"):
        envs.create("Robert'); DROP TABLE", REFUND_ENV, {})


def test_serial_ids_continue_after_pinned_seed(envs: FixturePool) -> None:
    seed: dict[str, list[Row]] = {**SEED, "approvals": [{"id": 7, "order_id": "ORD-1", "status": "granted"}]}
    fx = envs.create("t_serial", REFUND_ENV, seed)
    try:
        assert fx.call("request_approval", {"order_id": "ORD-1"})[1] == {"approval_id": 8, "status": "granted"}
    finally:
        envs.drop("t_serial")


def test_bad_arguments_are_422_and_not_ledgered(envs: FixturePool, fixture_url: str) -> None:
    fx = envs.create("t_args", REFUND_ENV, SEED)
    try:
        for body in (
            {},
            {"order_id": 5},
            {"order_id": "ORD-1", "amount_cents": "5"},
            {"order_id": "O", "amount_cents": True},
        ):
            assert post(fixture_url, "t_args", "issue_refund", body).status_code == 422, body
        assert post(fixture_url, "t_args", "get_order", {"order_id": "ORD-1", "extra": 1}).status_code == 422
        assert post(fixture_url, "t_args", "issue_refund", {**REFUND, "idempotency_key": 3}).status_code == 422
        assert post(fixture_url, "t_args", "nope").status_code == 404
        assert fx.ledger() == []
    finally:
        envs.drop("t_args")


def test_rules_and_return_modes(envs: FixturePool, fixture_url: str) -> None:
    fx = envs.create("t_modes", REFUND_ENV, SEED)
    try:
        assert post(fixture_url, "t_modes", "get_order", {"order_id": "ORD-1"}).json() == {
            "id": "ORD-1",
            "customer_id": "C-1",
            "amount_cents": 500,
        }
        missing = post(fixture_url, "t_modes", "get_order", {"order_id": "ORD-9"})
        assert (missing.status_code, missing.json()) == (404, {"error": "order not found"})
        assert post(fixture_url, "t_modes", "issue_refund", {**REFUND, "order_id": "ORD-9"}).status_code == 404
        assert fx.query("SELECT COUNT(*) FROM refunds") == [(0,)]  # a fired rule has no effect
        refund = post(fixture_url, "t_modes", "issue_refund", REFUND)
        assert refund.status_code == 201
        assert refund.json()["id"] == 1
        assert post(fixture_url, "t_modes", "get_refunds", {"order_id": "ORD-1"}).json() == [refund.json()]
        assert post(fixture_url, "t_modes", "delete_customer", {"customer_id": "C-1"}).json() == {"deleted": "C-1"}
        assert [e.committed for e in fx.ledger()] == [False, False, False, True, False, True]  # reads never commit
    finally:
        envs.drop("t_modes")


def test_approval_follows_the_limit_setting(envs: FixturePool) -> None:
    fx = envs.create(
        "t_limit",
        REFUND_ENV,
        {**SEED, "orders": [{"id": "BIG", "customer_id": "C-1", "amount_cents": 5000}, *SEED["orders"]]},
    )
    try:
        assert fx.call("request_approval", {"order_id": "BIG"})[1]["status"] == "denied"  # ty: ignore[invalid-argument-type, not-subscriptable]
        assert fx.call("request_approval", {"order_id": "ORD-1"})[1]["status"] == "granted"  # ty: ignore[invalid-argument-type, not-subscriptable]
    finally:
        envs.drop("t_limit")


def test_idempotency_key_replays_arg_or_header(envs: FixturePool, fixture_url: str) -> None:
    fx = envs.create("t_idem", REFUND_ENV, SEED)
    try:
        first = post(fixture_url, "t_idem", "issue_refund", REFUND, **{"Idempotency-Key": "k"})
        again = post(fixture_url, "t_idem", "issue_refund", {**REFUND, "idempotency_key": "k"})
        assert (first.status_code, again.status_code, again.json()) == (201, 201, first.json())
        assert fx.query("SELECT COUNT(*) FROM refunds") == [(1,)]
        other = post(fixture_url, "t_idem", "issue_refund", {**REFUND, "idempotency_key": "k2"})
        assert other.json()["id"] == 2
        assert fx.call("get_order", {"order_id": "ORD-1", "idempotency_key": "k"})[0] == 422  # not an idempotent tool
    finally:
        envs.drop("t_idem")


def test_timeout_after_commit_commits_then_fails(envs: FixturePool, fixture_url: str) -> None:
    fx = envs.create("t_timeout", REFUND_ENV, SEED, TIMEOUT)
    try:
        assert post(fixture_url, "t_timeout", "issue_refund", REFUND).status_code == 504
        assert post(fixture_url, "t_timeout", "issue_refund", REFUND).status_code == 201
        assert fx.query("SELECT COUNT(*) FROM refunds") == [(2,)]
        assert [(e.status, e.committed) for e in fx.ledger()] == [(504, True), (201, True)]
    finally:
        envs.drop("t_timeout")


def test_retry_with_key_after_timeout_does_not_duplicate(envs: FixturePool, fixture_url: str) -> None:
    fx = envs.create("t_retry", REFUND_ENV, SEED, TIMEOUT)
    try:
        body = {**REFUND, "idempotency_key": "k"}
        assert post(fixture_url, "t_retry", "issue_refund", body).status_code == 504
        assert post(fixture_url, "t_retry", "issue_refund", body).status_code == 201
        assert fx.query("SELECT COUNT(*) FROM refunds") == [(1,)]
    finally:
        envs.drop("t_retry")


def test_error_before_commit_has_no_side_effect(envs: FixturePool, fixture_url: str) -> None:
    fx = envs.create("t_before", REFUND_ENV, SEED, [ToolFault(tool="issue_refund", action="error_before_commit")])
    try:
        assert post(fixture_url, "t_before", "issue_refund", REFUND).status_code == 503
        assert fx.query("SELECT COUNT(*) FROM refunds") == [(0,)]
        assert not fx.ledger()[0].committed
    finally:
        envs.drop("t_before")


def test_environments_are_isolated(envs: FixturePool, fixture_url: str) -> None:
    a, b = envs.create("t_iso_a", REFUND_ENV, SEED), envs.create("t_iso_b", REFUND_ENV, SEED)
    try:
        post(fixture_url, "t_iso_a", "issue_refund", REFUND)
        assert a.query("SELECT COUNT(*) FROM refunds") == [(1,)]
        assert b.query("SELECT COUNT(*) FROM refunds") == [(0,)]
    finally:
        envs.drop("t_iso_a")
        envs.drop("t_iso_b")


def test_assertion_queries_are_read_only(envs: FixturePool) -> None:
    fx = envs.create("t_ro", REFUND_ENV, SEED)
    try:
        with pytest.raises(psycopg.Error):
            fx.query("DELETE FROM orders")
        assert fx.query("SELECT COUNT(*) FROM orders") == [(1,)]
        assert fx.query("SELECT COUNT(*) FROM ledger") == [(0,)]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            fx.query("SELECT COUNT(*) FROM idempotency")
    finally:
        envs.drop("t_ro")


def test_restore_replays_committed_history_including_idempotency(envs: FixturePool, fixture_url: str) -> None:
    src = envs.create("t_src", REFUND_ENV, SEED, TIMEOUT)
    try:
        post(fixture_url, "t_src", "request_approval", {"order_id": "ORD-1"})
        post(fixture_url, "t_src", "issue_refund", {**REFUND, "idempotency_key": "k"})  # commits, reports 504
        history = src.ledger()
        restored = envs.create("t_dst", REFUND_ENV, SEED, TIMEOUT, history)
        assert restored.state() == src.state()
        assert [e.tool for e in restored.ledger()] == [e.tool for e in history]
        # the fault already fired in history, and the stored key still replays instead of refunding again
        retry = post(fixture_url, "t_dst", "issue_refund", {**REFUND, "idempotency_key": "k"})
        assert retry.status_code == 201
        assert restored.query("SELECT COUNT(*) FROM refunds") == [(1,)]
    finally:
        envs.drop("t_src")
        envs.drop("t_dst")


def test_unknown_env_404_and_drop_removes_it(envs: FixturePool, fixture_url: str) -> None:
    assert post(fixture_url, "nope", "get_order", {"order_id": "x"}).status_code == 404
    assert httpx.get(f"{fixture_url}/env/nope/tools").status_code == 404
    envs.create("t_drop", REFUND_ENV, {})
    envs.drop("t_drop")
    with pytest.raises(KeyError):
        envs.get("t_drop")


def test_runner_server_exposes_no_admin_routes(envs: FixturePool, fixture_url: str) -> None:
    envs.create("t_admin", REFUND_ENV, {})
    try:
        assert httpx.post(f"{fixture_url}/env/t_admin/admin/reset", json={}).status_code == 404
        assert httpx.get(f"{fixture_url}/env/t_admin/admin/state").status_code == 404
        assert httpx.post(f"{fixture_url}/env/t_admin/refunds", json=REFUND).status_code == 404  # old routes are gone
    finally:
        envs.drop("t_admin")


def test_catalog_lists_tools_with_idempotency_key(envs: FixturePool, fixture_url: str) -> None:
    envs.create("t_cat", REFUND_ENV, {})
    try:
        body = httpx.get(f"{fixture_url}/env/t_cat/tools").json()
        assert body == catalog(REFUND_ENV).model_dump(mode="json")
        tools = {t["name"]: t["parameters"] for t in body["tools"]}
        assert tools["issue_refund"]["properties"]["idempotency_key"]["type"] == "string"
        assert "idempotency_key" not in tools["get_order"]["properties"]
        assert tools["issue_refund"]["required"] == ["order_id", "amount_cents"]
    finally:
        envs.drop("t_cat")


def hostile(tool_sql: str) -> EnvironmentSpec:
    """A refund environment plus one tool whose SQL tries to break out."""
    raw = REFUND_ENV.model_dump(mode="json")
    raw["tools"].append(
        {"name": "evil", "description": "x", "params": [{"name": "v", "type": "string"}], "sql": tool_sql}
    )
    return EnvironmentSpec.model_validate(raw)


def test_writer_role_is_contained(envs: FixturePool) -> None:
    other = envs.create("t_w_other", REFUND_ENV, SEED)
    attacks = [
        "SELECT count(*) AS n FROM ledger",
        "DELETE FROM ledger",
        "SELECT count(*) AS n FROM idempotency",
        "INSERT INTO idempotency VALUES ('k', 't', 200, '{}')",
        "SELECT count(*) AS n FROM agentlab.trials",
        "SELECT count(*) AS n FROM env_t_w_other.orders",
        "SELECT set_config('role', 'none', true), query_to_xml('SELECT count(*) FROM agentlab.trials', true, true, '')",
        "SELECT query_to_xml('SELECT count(*) FROM ledger', true, true, '')",
        "SELECT query_to_xml('SELECT count(*) FROM env_t_w_other.orders', true, true, '')",
        "TRUNCATE orders",
        "CREATE TABLE evil (a int)",
        "SELECT nextval('ledger_seq_seq')",
    ]
    for i, attack in enumerate(attacks):
        fx = envs.create("t_w_a", hostile(attack), SEED)
        try:
            fx.call("get_order", {"order_id": "ORD-1"})
            status, body = fx.call("evil", {"v": "x"})
            assert status == 500, (attack, body)
            assert "database error" in str(body)
            assert fx.query("SELECT COUNT(*) FROM orders") == [(1,)]
            assert [e.tool for e in fx.ledger()] == ["get_order", "evil"], i
        finally:
            envs.drop("t_w_a")
    assert other.query("SELECT COUNT(*) FROM orders") == [(1,)]
    envs.drop("t_w_other")


def test_params_cannot_inject_sql(envs: FixturePool) -> None:
    fx = envs.create("t_inject", REFUND_ENV, SEED)
    try:
        evil = "ORD-1'; DELETE FROM orders; --"
        assert fx.call("get_order", {"order_id": evil})[0] == 404
        assert fx.call("issue_refund", {"order_id": evil, "amount_cents": 1})[0] == 404
        assert fx.query("SELECT COUNT(*) FROM orders") == [(1,)]
        fx.call("request_approval", {"order_id": "ORD-1", "reason": evil})
        assert fx.query("SELECT COUNT(*) FROM approvals") == [(1,)]
    finally:
        envs.drop("t_inject")


def test_multi_statement_tool_sql_is_rejected(envs: FixturePool) -> None:
    fx = envs.create("t_multi", hostile("DELETE FROM orders; DELETE FROM customers"), SEED)
    try:
        assert fx.call("evil", {"v": "x"})[0] == 500
        assert fx.query("SELECT COUNT(*) FROM orders") == [(1,)]
        assert fx.tool_errors()
    finally:
        envs.drop("t_multi")


def test_author_sql_cannot_escape_its_environment(envs: FixturePool) -> None:
    mine = envs.create("t_sbx_a", REFUND_ENV, SEED)
    envs.create("t_sbx_b", REFUND_ENV, SEED)
    try:
        assert mine.query("SELECT COUNT(*) FROM orders") == [(1,)]
        for escape in (
            "SELECT COUNT(*) FROM agentlab.trials",
            "SELECT COUNT(*) FROM env_t_sbx_b.orders",
            "SELECT set_config('role', 'none', true), "
            "query_to_xml('SELECT count(*) FROM agentlab.trials', true, true, '')",
            "SELECT query_to_xml('SELECT count(*) FROM env_t_sbx_b.orders', true, true, '')",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                mine.query(escape)
        for shed_role in (
            "SELECT 1; SELECT 2",
            "RESET ROLE; SELECT COUNT(*) FROM agentlab.trials",
            "RESET ROLE",
            "SET ROLE NONE",
        ):
            with pytest.raises(psycopg.Error):
                mine.query(shed_role)
        assert mine.query("WITH o AS (SELECT * FROM orders) SELECT COUNT(*) FROM o;") == [(1,)]
    finally:
        envs.drop("t_sbx_a")
        envs.drop("t_sbx_b")


def test_travel_end_to_end(envs: FixturePool, fixture_url: str) -> None:
    fx = envs.create(
        "t_travel", TRAVEL_ENV, TRAVEL_SEED, [ToolFault(tool="charge_payment", action="timeout_after_commit")]
    )
    try:
        flights = post(fixture_url, "t_travel", "search_flights", {"origin": "SFO"}).json()
        assert [f["id"] for f in flights] == ["FL-1"]
        assert post(fixture_url, "t_travel", "search_flights", {"origin": "LAX"}).json() == []
        booking = post(fixture_url, "t_travel", "create_booking", {"flight_id": "FL-1", "passenger": "Ada"})
        assert (booking.status_code, booking.json()["booking_id"]) == (201, 1)
        full = post(fixture_url, "t_travel", "create_booking", {"flight_id": "FL-1", "passenger": "Bob"})
        assert (full.status_code, full.json()) == (409, {"error": "no seats left"})
        charge = {"booking_id": 1, "amount_cents": 900, "idempotency_key": "pay-1"}
        assert post(fixture_url, "t_travel", "charge_payment", charge).status_code == 504
        assert post(fixture_url, "t_travel", "charge_payment", charge).status_code == 201
        assert fx.query("SELECT COUNT(*) FROM payments") == [(1,)]
        assert fx.query("SELECT seats_left FROM flights") == [(0,)]
        assert post(fixture_url, "t_travel", "cancel_booking", {"booking_id": 1}).status_code == 200
        assert post(fixture_url, "t_travel", "cancel_booking", {"booking_id": 1}).status_code == 409
        assert post(fixture_url, "t_travel", "cancel_booking", {"booking_id": 9}).status_code == 404
        assert fx.query("SELECT seats_left FROM flights") == [(1,)]
        assert [b["status"] for b in post(fixture_url, "t_travel", "get_bookings", {"passenger": "Ada"}).json()] == [
            "cancelled"
        ]
    finally:
        envs.drop("t_travel")


def test_shipped_environments_validate_and_scenarios_fit_them(envs: FixturePool) -> None:
    for spec in (REFUND_ENV, TRAVEL_ENV):
        fx = envs.create("t_valid", spec, {})
        try:
            assert fx.tool_errors() == []
        finally:
            envs.drop("t_valid")
    for scenario in load_suite(ROOT / "scenarios"):
        spec = {"refund@1": REFUND_ENV, "travel@1": TRAVEL_ENV}[scenario.environment]
        envs.create("t_valid", spec, scenario.seed)
        envs.drop("t_valid")
