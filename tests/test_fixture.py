import httpx
import psycopg
import pytest

from agentlab.fixture import FixturePool, Seed
from agentlab.protocol import ToolFault
from agentlab.store import Store

SEED = Seed(
    customers=[{"id": "C-1", "name": "Ada"}], orders=[{"id": "ORD-1", "customer_id": "C-1", "amount_cents": 500}]
)
REFUND = {"order_id": "ORD-1", "amount_cents": 500}


def test_timeout_after_commit_commits_then_fails(envs: FixturePool, fixture_url: str) -> None:
    fx = envs.create("t_timeout", SEED, [ToolFault(tool="issue_refund", action="timeout_after_commit")])
    try:
        assert httpx.post(f"{fixture_url}/env/t_timeout/refunds", json=REFUND).status_code == 504
        assert httpx.post(f"{fixture_url}/env/t_timeout/refunds", json=REFUND).status_code == 201
        assert fx.query("SELECT COUNT(*) FROM refunds") == [(2,)]
        assert [(e.status, e.committed) for e in fx.ledger()] == [(504, True), (201, True)]
    finally:
        envs.drop("t_timeout")


def test_error_before_commit_has_no_side_effect(envs: FixturePool, fixture_url: str) -> None:
    fx = envs.create("t_before", SEED, [ToolFault(tool="issue_refund", action="error_before_commit")])
    try:
        assert httpx.post(f"{fixture_url}/env/t_before/refunds", json=REFUND).status_code == 503
        assert fx.query("SELECT COUNT(*) FROM refunds") == [(0,)]
        assert not fx.ledger()[0].committed
    finally:
        envs.drop("t_before")


def test_idempotency_key_dedupes(envs: FixturePool, fixture_url: str) -> None:
    fx = envs.create("t_idem", SEED)
    try:
        for _ in range(2):
            httpx.post(f"{fixture_url}/env/t_idem/refunds", json=REFUND, headers={"Idempotency-Key": "k"})
        assert fx.query("SELECT COUNT(*) FROM refunds") == [(1,)]
    finally:
        envs.drop("t_idem")


def test_environments_are_isolated(envs: FixturePool, fixture_url: str) -> None:
    a, b = envs.create("t_iso_a", SEED), envs.create("t_iso_b", SEED)
    try:
        httpx.post(f"{fixture_url}/env/t_iso_a/refunds", json=REFUND)
        assert a.query("SELECT COUNT(*) FROM refunds") == [(1,)]
        assert b.query("SELECT COUNT(*) FROM refunds") == [(0,)]
    finally:
        envs.drop("t_iso_a")
        envs.drop("t_iso_b")


def test_assertion_queries_are_read_only(envs: FixturePool) -> None:
    fx = envs.create("t_ro", SEED)
    try:
        with pytest.raises(psycopg.Error):  # rejected by the SELECT wrapper; the read-only tx is a second layer
            fx.query("DELETE FROM orders")
        assert fx.query("SELECT COUNT(*) FROM orders") == [(1,)]
    finally:
        envs.drop("t_ro")


def test_restore_replays_committed_history(envs: FixturePool, fixture_url: str) -> None:
    src = envs.create("t_src", SEED, [ToolFault(tool="issue_refund", action="timeout_after_commit")])
    try:
        httpx.post(f"{fixture_url}/env/t_src/approvals", json={"order_id": "ORD-1"})
        httpx.post(f"{fixture_url}/env/t_src/refunds", json=REFUND)  # commits, reports 504
        history = src.ledger()
        restored = envs.create("t_dst", SEED, [ToolFault(tool="issue_refund", action="timeout_after_commit")], history)
        assert restored.state() == src.state()
        assert [e.tool for e in restored.ledger()] == [e.tool for e in history]
        # first_call already happened in history, so the fault does not fire again
        assert httpx.post(f"{fixture_url}/env/t_dst/refunds", json=REFUND).status_code == 201
    finally:
        envs.drop("t_src")
        envs.drop("t_dst")


def test_unknown_env_404_and_bad_ids_rejected(envs: FixturePool, fixture_url: str) -> None:
    assert httpx.get(f"{fixture_url}/env/nope/orders/ORD-1").status_code == 404
    with pytest.raises(ValueError, match="invalid environment id"):
        envs.create("Robert'); DROP TABLE", SEED)
    with pytest.raises(ValueError, match="unknown customers column"):
        envs.create("t_badcol", Seed(customers=[{"id": "C", "name": "x", "evil": "1"}]))
    envs.drop("t_badcol")


def test_drop_removes_schema(envs: FixturePool, db: object) -> None:
    envs.create("t_drop", SEED)
    envs.drop("t_drop")
    with pytest.raises(KeyError):
        envs.get("t_drop")


def test_runner_server_exposes_no_admin_routes(envs: FixturePool, fixture_url: str) -> None:
    # Agents under test share the runner's fixture server; they must not reset or read environments.
    envs.create("t_admin", SEED)
    try:
        assert httpx.post(f"{fixture_url}/env/t_admin/admin/reset", json={}).status_code == 404
        assert httpx.get(f"{fixture_url}/env/t_admin/admin/state").status_code == 404
    finally:
        envs.drop("t_admin")


def test_author_sql_cannot_escape_its_environment(envs: FixturePool, store: Store) -> None:
    mine = envs.create("t_sbx_a", SEED)
    envs.create("t_sbx_b", SEED)
    try:
        assert mine.query("SELECT COUNT(*) FROM orders") == [(1,)]  # its own schema is readable
        for escape in (
            "SELECT COUNT(*) FROM agentlab.trials",  # stored results
            "SELECT COUNT(*) FROM env_t_sbx_b.orders",  # another trial's environment
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                mine.query(escape)
        for shed_role in (
            "SELECT 1; SELECT 2",  # one statement only
            "RESET ROLE; SELECT COUNT(*) FROM agentlab.trials",
            "RESET ROLE",
            "SET ROLE NONE",
        ):
            with pytest.raises(psycopg.Error):
                mine.query(shed_role)
        assert mine.query("WITH o AS (SELECT * FROM orders) SELECT COUNT(*) FROM o;") == [(1,)]  # CTEs still work
    finally:
        envs.drop("t_sbx_a")
        envs.drop("t_sbx_b")
