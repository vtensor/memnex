"""CLI bug regression: `memnex serve mcp --transport stdio` must build a
TenantStore (not a Memnex client) and not crash on boot.

The earlier bug passed a ``Memnex`` instance into ``run_stdio``, which
calls ``store.resolve_key(...)`` on its argument. Memnex has no such
method, so the first invocation crashed with ``AttributeError``.
Tests bypassed this because they construct ``McpContext`` directly.
"""
from __future__ import annotations

from memnex.saas.accounts import TenantStore
from memnex.saas.bootstrap import bootstrap_store_from_env


def test_bootstrap_returns_tenant_store(monkeypatch):
    monkeypatch.delenv("MEMNEX_DEV_KEY", raising=False)
    store = bootstrap_store_from_env()
    assert isinstance(store, TenantStore)


def test_bootstrap_dev_mode_seeds_a_key(monkeypatch, capsys):
    monkeypatch.setenv("MEMNEX_DEV_KEY", "1")
    store = bootstrap_store_from_env()
    err = capsys.readouterr().err
    assert "MEMNEX_SECRET_KEY=mx_live_" in err
    # store should have one tenant + one key
    assert len(store._by_id) == 1
    assert len(store._by_key_id) == 1


def test_bootstrap_dev_mode_disabled_when_unset(monkeypatch):
    monkeypatch.delenv("MEMNEX_DEV_KEY", raising=False)
    store = bootstrap_store_from_env()
    assert len(store._by_id) == 0
    assert len(store._by_key_id) == 0


def test_serve_mcp_does_not_pass_memnex_to_run_stdio(monkeypatch):
    """Direct regression: serve_mcp must invoke run_stdio with a TenantStore.

    We monkeypatch run_stdio to capture its argument and confirm the type.
    """
    captured = {}

    async def fake_run_stdio(arg):
        captured["arg"] = arg

    monkeypatch.setenv("MEMNEX_DEV_KEY", "1")
    import memnex.mcp.server as server_mod
    monkeypatch.setattr(server_mod, "run_stdio", fake_run_stdio)

    from click.testing import CliRunner

    from memnex.cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["serve", "mcp", "--transport", "stdio"])
    assert result.exit_code == 0, result.output
    assert isinstance(captured.get("arg"), TenantStore)
