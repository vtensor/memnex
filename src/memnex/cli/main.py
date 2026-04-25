"""memnex CLI."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import click

from memnex.client import Memnex
from memnex.config import MemnexConfig


def _config_from_env() -> MemnexConfig:
    return MemnexConfig.from_env()


async def _make_client() -> Memnex:
    return await Memnex.create(config=_config_from_env())


@click.group()
@click.version_option()
def cli() -> None:
    """Memnex — cross-channel memory for conversational agents."""


# --------------------- serve ---------------------
@cli.group()
def serve() -> None:
    """Run Memnex as a server."""


@serve.command("mcp")
@click.option("--transport", type=click.Choice(["stdio", "streamable-http"]), default="stdio")
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8500, type=int)
def serve_mcp(transport: str, host: str, port: int) -> None:
    """Run the MCP server."""
    from memnex.mcp.server import run_stdio, run_streamable_http
    from memnex.saas.bootstrap import bootstrap_store_from_env

    store = bootstrap_store_from_env()

    if transport == "stdio":
        asyncio.run(run_stdio(store))
    else:
        asyncio.run(run_streamable_http(store, host=host, port=port))


@serve.command("rest")
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8500, type=int)
def serve_rest(host: str, port: int) -> None:
    """Run the REST API."""
    try:
        import uvicorn
    except ImportError as e:
        raise click.ClickException("`pip install memnex[api]`.") from e
    from memnex.api.app import build_app

    app = build_app(_config_from_env())
    uvicorn.run(app, host=host, port=port)


# --------------------- db ---------------------
@cli.group()
def db() -> None:
    """Database management."""


@db.command("init")
def db_init() -> None:
    """Create tables, RLS policies, and indexes."""
    asyncio.run(_run_migrations(list(_migration_files())))


async def _run_migrations(paths: list[Path]) -> None:
    url = os.getenv("MEMNEX_POSTGRES_URL")
    if not url:
        raise click.ClickException("MEMNEX_POSTGRES_URL is not set.")
    try:
        import asyncpg
    except ImportError as e:
        raise click.ClickException("`pip install memnex[postgres]`.") from e

    conn = await asyncpg.connect(url)
    try:
        for p in paths:
            click.echo(f"running {p.name}...")
            await conn.execute(p.read_text())
    finally:
        await conn.close()
    click.echo("migrations complete.")


def _migration_files() -> list[Path]:
    base = Path(__file__).resolve().parent.parent / "storage" / "migrations"
    return sorted(base.glob("*.sql"))


@db.command("migrate")
def db_migrate() -> None:
    """Alias of init — idempotent."""
    asyncio.run(_run_migrations(list(_migration_files())))


@db.command("vacuum")
def db_vacuum() -> None:
    """Expire TTL'd memories."""
    async def _go() -> None:
        mx = await _make_client()
        try:
            from memnex.privacy.ttl import enforce
            n = await enforce(mx._stores.warm)
            click.echo(f"expired {n} memories")
        finally:
            await mx.close()

    asyncio.run(_go())


# --------------------- memory ---------------------
@cli.command("write")
@click.option("--channel", required=True)
@click.option("--id", "identifier", required=True)
@click.option("--fact", "facts", multiple=True)
@click.option("--raw-text", default=None)
def write_cmd(channel: str, identifier: str, facts: tuple[str, ...], raw_text: str | None) -> None:
    """Write facts for a customer."""
    async def _go() -> None:
        mx = await _make_client()
        try:
            result = await mx.write(
                channel=channel,
                identifier=identifier,
                facts=list(facts) if facts else None,
                raw_text=raw_text,
            )
            click.echo(json.dumps({"written": len(result), "ids": [m.memory_id for m in result]}))
        finally:
            await mx.close()

    asyncio.run(_go())


@cli.command("read")
@click.option("--channel", required=True)
@click.option("--id", "identifier", required=True)
@click.option("--target", "target_channel", default=None)
@click.option("--budget", default=2000, type=int)
def read_cmd(channel: str, identifier: str, target_channel: str | None, budget: int) -> None:
    async def _go() -> None:
        mx = await _make_client()
        try:
            ctx = await mx.read(
                channel=channel,
                identifier=identifier,
                target_channel=target_channel,
                token_budget=budget,
            )
            click.echo(ctx)
        finally:
            await mx.close()

    asyncio.run(_go())


@cli.command("search")
@click.option("--channel", required=True)
@click.option("--id", "identifier", required=True)
@click.option("--query", required=True)
@click.option("--max-results", default=5, type=int)
def search_cmd(channel: str, identifier: str, query: str, max_results: int) -> None:
    async def _go() -> None:
        mx = await _make_client()
        try:
            results = await mx.search(
                channel=channel, identifier=identifier, query=query, max_results=max_results
            )
            for m in results:
                click.echo(f"- [{m.fact_type}] {m.fact} (salience={m.salience:.2f})")
        finally:
            await mx.close()

    asyncio.run(_go())


# --------------------- identity ---------------------
@cli.group()
def identity() -> None:
    """Identity commands."""


@identity.command("resolve")
@click.option("--channel", required=True)
@click.option("--id", "identifier", required=True)
def identity_resolve(channel: str, identifier: str) -> None:
    async def _go() -> None:
        mx = await _make_client()
        try:
            customer = await mx.resolve(channel, identifier)
            click.echo(customer.model_dump_json(indent=2))
        finally:
            await mx.close()

    asyncio.run(_go())


@identity.command("link")
@click.option("--from", "src", required=True, help="channel:identifier")
@click.option("--to", "dst", required=True, help="channel:identifier")
def identity_link(src: str, dst: str) -> None:
    async def _go() -> None:
        mx = await _make_client()
        try:
            sc, _, sid = src.partition(":")
            dc, _, did = dst.partition(":")
            customer = await mx.resolve(sc, sid)
            await mx.link_identity(customer_id=customer.id, channel=dc, identifier=did)
            click.echo(f"linked to customer_id={customer.id}")
        finally:
            await mx.close()

    asyncio.run(_go())


@identity.command("graph")
@click.option("--customer", required=True)
def identity_graph(customer: str) -> None:
    async def _go() -> None:
        mx = await _make_client()
        try:
            idents = await mx._stores.warm.list_identifiers(mx.config.tenant_id, customer)
            click.echo(json.dumps([i.model_dump(mode="json") for i in idents], indent=2))
        finally:
            await mx.close()

    asyncio.run(_go())


# --------------------- admin ---------------------
@cli.command("stats")
def stats_cmd() -> None:
    async def _go() -> None:
        mx = await _make_client()
        try:
            click.echo(json.dumps(await mx.stats(), indent=2))
        finally:
            await mx.close()

    asyncio.run(_go())


@cli.command("export")
@click.option("--customer", required=True)
@click.option("--format", default="json", type=click.Choice(["json"]))
def export_cmd(customer: str, format: str) -> None:
    async def _go() -> None:
        mx = await _make_client()
        try:
            data = await mx.export_customer_data(customer_id=customer, format=format)
            click.echo(json.dumps(data, indent=2, default=str))
        finally:
            await mx.close()

    asyncio.run(_go())


@cli.command("forget")
@click.option("--customer", required=True)
@click.option("--reason", default="gdpr_request")
def forget_cmd(customer: str, reason: str) -> None:
    async def _go() -> None:
        mx = await _make_client()
        try:
            receipt = await mx.forget_customer(customer_id=customer, reason=reason)
            click.echo(json.dumps(receipt, indent=2))
        finally:
            await mx.close()

    asyncio.run(_go())


# --------------------- eval ---------------------
@cli.command("eval")
@click.option("--suite", default="full",
              type=click.Choice(["full", "identity_resolution", "recall", "handoff", "latency", "conflict", "load"]))
@click.option("--output", default=None)
@click.option("--agents", default=1000, type=int, help="for load suite")
def eval_cmd(suite: str, output: str | None, agents: int) -> None:
    from memnex.eval.runner import run_suite

    async def _go() -> None:
        mx = await _make_client()
        try:
            results = await run_suite(mx, suite=suite, load_agents=agents)
            rendered = json.dumps(results, indent=2, default=str)
            if output:
                Path(output).write_text(rendered)
            click.echo(rendered)
        finally:
            await mx.close()

    asyncio.run(_go())


if __name__ == "__main__":
    try:
        cli()
    except Exception as e:  # pragma: no cover
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
