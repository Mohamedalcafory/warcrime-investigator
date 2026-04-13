"""Typer CLI: investigate fetch | list | search | summarize | extract."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from investigation_agent.config import telegram_channels
from investigation_agent.db.session import get_session_factory, init_db
from investigation_agent.db.schema import Evidence
from investigation_agent.db.store import (
    add_search_run,
    get_evidence_by_ids,
    get_evidence_by_target,
    insert_evidence,
    list_evidence,
    list_evidence_by_review_status,
    search_evidence_text,
    set_review_status,
    update_classification_json,
)
from investigation_agent.retrieval.chroma_store import index_evidence_safe, semantic_search as chroma_semantic_search
from investigation_agent.llm.json_util import parse_json_object
from investigation_agent.llm.ollama_client import OllamaChatError, chat_completion
from investigation_agent.llm.prompts import (
    EXTRACT_SYSTEM,
    SUMMARIZE_SYSTEM,
    build_evidence_context,
    extract_user_prompt,
    summarize_user_prompt,
)
from investigation_agent.scraper.telegram import search_channels_for_target
from investigation_agent.scraper.web import fetch_web_for_target

app = typer.Typer(help="Target-driven evidence collection (Telegram search + web)")
review_app = typer.Typer(help="Analyst review status for evidence rows")
app.add_typer(review_app, name="review")
console = Console()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


@app.callback()
def main() -> None:
    init_db()


@app.command("fetch")
def cmd_fetch(
    target: Annotated[str, typer.Argument(help="Hospital, school, or other target to search for")],
    lang: Annotated[str, typer.Option("--lang", "-l", help="Hint for web search: en or ar")] = "en",
    max_web: Annotated[int, typer.Option("--max-web", help="Max DuckDuckGo results to process")] = 15,
    web: Annotated[bool, typer.Option("--web/--no-web", help="Include web search")] = True,
    telegram: Annotated[bool, typer.Option("--telegram/--no-telegram", help="Search Telegram channels")] = True,
) -> None:
    """Search Telegram (per-channel search) and the web for the target; store evidence in SQLite."""
    Session = get_session_factory()
    session = Session()
    try:
        run = add_search_run(
            session,
            target_query=target,
            language=lang,
            include_telegram=telegram,
            include_web=web,
            max_web_results=max_web,
        )
        session.commit()
        run_id = run.id
        added_tg = 0
        added_web = 0

        if telegram:
            channels = telegram_channels()
            try:
                hits = asyncio.run(
                    search_channels_for_target(
                        channels=channels,
                        search_query=target,
                        limit_per_channel=50,
                    )
                )
            except RuntimeError as e:
                console.print(f"[yellow]Telegram skipped:[/yellow] {e}")
                hits = []
            for h in hits:
                row = insert_evidence(
                    session,
                    search_run_id=run_id,
                    target_query=target,
                    source_type="telegram",
                    source_url=h.url,
                    raw_text=h.text,
                    title=None,
                    snippet=h.text[:500] if h.text else None,
                    channel_username=h.channel_username,
                    message_id=h.message_id,
                    fetch_status="ok",
                )
                if row:
                    added_tg += 1
            session.commit()

        if web:
            try:
                web_hits = fetch_web_for_target(query=target, max_results=max_web, lang=lang)
            except Exception as e:
                console.print(f"[red]Web search failed:[/red] {e}")
                web_hits = []
            for wh in web_hits:
                row = insert_evidence(
                    session,
                    search_run_id=run_id,
                    target_query=target,
                    source_type="web",
                    source_url=wh.url,
                    raw_text=wh.raw_text,
                    title=wh.title or None,
                    snippet=wh.snippet or None,
                    serp_rank=wh.rank,
                    serp_snippet=wh.snippet,
                    fetch_status=wh.fetch_status,
                    published_at=wh.published_at,
                )
                if row:
                    added_web += 1
            session.commit()

        console.print(
            f"[green]Done[/green] run_id={run_id} "
            f"telegram+{added_tg} web+{added_web} "
            f"(target={target!r})"
        )
    finally:
        session.close()


@app.command("list")
def cmd_list(
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Filter by target substring"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows")] = 50,
) -> None:
    """List stored evidence (most recent first)."""
    Session = get_session_factory()
    session = Session()
    try:
        rows = list_evidence(session, target_substring=target, limit=limit)
        if not rows:
            console.print("No evidence yet. Run [bold]investigate fetch \"...\"[/bold]")
            return
        table = Table(title="Evidence")
        table.add_column("id", style="cyan")
        table.add_column("type")
        table.add_column("review")
        table.add_column("target")
        table.add_column("url", overflow="fold")
        table.add_column("status")
        for r in rows:
            table.add_row(
                str(r.id),
                r.source_type,
                getattr(r, "review_status", "pending"),
                (r.target_query[:40] + "…") if len(r.target_query) > 40 else r.target_query,
                r.source_url[:80] + ("…" if len(r.source_url) > 80 else ""),
                r.fetch_status,
            )
        console.print(table)
    finally:
        session.close()


@app.command("search")
def cmd_search(
    query: Annotated[str, typer.Argument(help="Substring search in stored title/text")],
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Only evidence whose target matches"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 30,
) -> None:
    """Search stored evidence text (SQLite ILIKE)."""
    Session = get_session_factory()
    session = Session()
    try:
        rows = search_evidence_text(session, query=query, target_substring=target, limit=limit)
        if not rows:
            console.print("No matches.")
            return
        for r in rows:
            console.print(f"[bold]{r.id}[/bold] {r.source_type} {r.source_url}")
            preview = (r.raw_text or "")[:300].replace("\n", " ")
            console.print(f"  {preview}…")
    finally:
        session.close()


@app.command("semantic-search")
def cmd_semantic_search(
    query: Annotated[str, typer.Argument(help="Natural-language query for semantic similarity")],
    target: Annotated[
        Optional[str],
        typer.Option("--target", "-t", help="Only rows whose target_query contains this substring"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max results")] = 15,
) -> None:
    """Search stored evidence by meaning (ChromaDB embeddings)."""
    n_fetch = min(limit * 5, 100) if target else limit
    hits = chroma_semantic_search(query, limit=n_fetch)
    Session = get_session_factory()
    session = Session()
    try:
        shown = 0
        for h in hits:
            r = session.get(Evidence, h.evidence_id)
            if r is None:
                continue
            if target and target.lower() not in (r.target_query or "").lower():
                continue
            dist = h.distance if h.distance is not None else 0.0
            console.print(f"[bold]{h.evidence_id}[/bold] distance={dist:.4f} {r.source_type} {r.source_url}", markup=False)
            preview = (r.raw_text or h.preview or "")[:320].replace("\n", " ")
            console.print(f"  {preview}…")
            shown += 1
            if shown >= limit:
                break
        if shown == 0:
            console.print(
                "No matches. If you upgraded from an older version, run: [bold]investigate reindex[/bold]"
            )
    finally:
        session.close()


@app.command("reindex")
def cmd_reindex(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max evidence rows to index")] = 2000,
) -> None:
    """Backfill ChromaDB from SQLite (for DBs created before semantic indexing)."""
    Session = get_session_factory()
    session = Session()
    try:
        rows = list_evidence(session, target_substring=None, limit=limit)
        n = 0
        for r in rows:
            index_evidence_safe(
                r.id,
                title=r.title,
                raw_text=r.raw_text or "",
                target_query=r.target_query,
                source_type=r.source_type,
                source_url=r.source_url,
            )
            n += 1
        console.print(f"[green]Indexed[/green] {n} evidence row(s) into Chroma.")
    finally:
        session.close()


@review_app.command("set")
def cmd_review_set(
    ids: Annotated[str, typer.Option("--ids", help="Comma-separated evidence ids")],
    status: Annotated[str, typer.Option("--status", help="pending | approved | rejected")],
) -> None:
    """Set review status for evidence rows."""
    if status not in ("pending", "approved", "rejected"):
        console.print("[red]status must be pending, approved, or rejected[/red]")
        raise typer.Exit(1)
    id_list = _parse_id_list(ids)
    if not id_list:
        console.print("[red]Provide --ids[/red]")
        raise typer.Exit(1)
    Session = get_session_factory()
    session = Session()
    try:
        n = set_review_status(session, id_list, status)
        session.commit()
        console.print(f"[green]Updated[/green] {n} row(s) to {status!r}")
    finally:
        session.close()


@review_app.command("list")
def cmd_review_list(
    status: Annotated[str, typer.Option("--status", help="pending | approved | rejected")] = "pending",
    limit: Annotated[int, typer.Option("--limit", "-n")] = 50,
) -> None:
    """List evidence filtered by review_status."""
    if status not in ("pending", "approved", "rejected"):
        console.print("[red]status must be pending, approved, or rejected[/red]")
        raise typer.Exit(1)
    Session = get_session_factory()
    session = Session()
    try:
        rows = list_evidence_by_review_status(session, status=status, limit=limit)
        if not rows:
            console.print("No rows.")
            return
        for r in rows:
            console.print(f"[bold]{r.id}[/bold] {r.review_status} {r.source_type} {r.source_url}", markup=False)
            preview = (r.raw_text or "")[:200].replace("\n", " ")
            console.print(f"  {preview}…")
    finally:
        session.close()


def _parse_id_list(ids_str: str | None) -> list[int]:
    if not ids_str or not ids_str.strip():
        return []
    out: list[int] = []
    for part in ids_str.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return out


@app.command("summarize")
def cmd_summarize(
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Filter evidence by target substring"),
    ] = None,
    ids: Annotated[
        str | None,
        typer.Option("--ids", help="Comma-separated evidence ids, e.g. 58,55,56"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows when using --target")] = 8,
    approved_only: Annotated[
        bool,
        typer.Option("--approved-only", help="Only include approved evidence (excludes pending and rejected)"),
    ] = False,
) -> None:
    """Summarize stored evidence with citation tags and source list (local Ollama)."""
    id_list = _parse_id_list(ids)
    if not id_list and not target:
        console.print("[red]Provide --target or --ids[/red]")
        raise typer.Exit(1)

    Session = get_session_factory()
    session = Session()
    try:
        if id_list:
            rows_all = get_evidence_by_ids(session, id_list)
            by_id = {r.id: r for r in rows_all}
            missing = [i for i in id_list if i not in by_id]
            if missing:
                console.print(f"[yellow]Missing evidence ids:[/yellow] {missing}")
            rows = []
            for i in id_list:
                r = by_id.get(i)
                if not r:
                    continue
                if approved_only:
                    if r.review_status != "approved":
                        continue
                elif r.review_status == "rejected":
                    continue
                rows.append(r)
            if not rows and rows_all:
                console.print("[yellow]No rows left after review filter (try without --approved-only).[/yellow]")
        else:
            assert target is not None
            rows = get_evidence_by_target(
                session,
                target_substring=target,
                limit=limit,
                approved_only=approved_only,
                exclude_rejected=not approved_only,
            )
        if not rows:
            console.print("No evidence to summarize.")
            raise typer.Exit(0)

        ctx = build_evidence_context(rows)
        try:
            out = chat_completion(
                [
                    {"role": "system", "content": SUMMARIZE_SYSTEM},
                    {"role": "user", "content": summarize_user_prompt(ctx)},
                ]
            )
        except OllamaChatError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(2)

        console.print(out)
        cited = {int(x) for x in re.findall(r"\[evidence:(\d+)\]", out)}
        by_id = {r.id: r for r in rows}
        if not cited:
            console.print(
                "\n[dim]No [evidence:ID] tags in model output; "
                "listing all sources in this batch for review.[/dim]"
            )
        console.print("\n[bold]Evidence sources (batch)[/bold]")
        for r in rows:
            # markup=False: avoid Rich interpreting [evidence:123] as style tags
            console.print(f"  id={r.id}  {r.source_url}", markup=False)
        if cited:
            console.print("\n[bold]Citations parsed from summary[/bold]")
            for eid in sorted(cited):
                if eid in by_id:
                    r = by_id[eid]
                    console.print(f"  id={eid}  {r.source_url}", markup=False)
                else:
                    console.print(f"  id={eid} (not in this batch)", style="yellow")
    finally:
        session.close()


@app.command("extract")
def cmd_extract(
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Filter evidence by target substring"),
    ] = None,
    ids: Annotated[
        str | None,
        typer.Option("--ids", help="Comma-separated evidence ids"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows when using --target")] = 20,
) -> None:
    """Run LLM extraction per evidence row; store JSON in classification_json (local Ollama)."""
    id_list = _parse_id_list(ids)
    if not id_list and not target:
        console.print("[red]Provide --target or --ids[/red]")
        raise typer.Exit(1)

    Session = get_session_factory()
    session = Session()
    try:
        if id_list:
            rows = get_evidence_by_ids(session, id_list)
        else:
            assert target is not None
            rows = get_evidence_by_target(session, target_substring=target, limit=limit)
        if not rows:
            console.print("No evidence to extract.")
            raise typer.Exit(0)

        for r in rows:
            user = extract_user_prompt(r.id, r.source_url, r.source_type, r.raw_text or "")
            llm_raw = ""
            try:
                llm_raw = chat_completion(
                    [
                        {"role": "system", "content": EXTRACT_SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.1,
                )
                data = parse_json_object(llm_raw)
                payload = json.dumps(data, ensure_ascii=False)
                update_classification_json(session, r.id, payload)
                session.commit()
                console.print(f"[green]ok[/green] id={r.id} facility_type={data.get('facility_type')!r}")
            except OllamaChatError as e:
                console.print(f"[red]id={r.id} Ollama:[/red] {e}")
                err = json.dumps({"error": "ollama", "message": str(e)}, ensure_ascii=False)
                update_classification_json(session, r.id, err)
                session.commit()
            except ValueError as e:
                console.print(f"[yellow]id={r.id} parse:[/yellow] {e}")
                err = json.dumps(
                    {"error": "parse_failed", "message": str(e), "raw": (llm_raw or "")[:2000]},
                    ensure_ascii=False,
                )
                update_classification_json(session, r.id, err)
                session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    app()
