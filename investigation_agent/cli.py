"""Typer CLI: investigate fetch | list | search | summarize | extract."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from investigation_agent.config import telegram_channels
from investigation_agent.db.session import get_session_factory, init_db
from investigation_agent.db.schema import Evidence
from investigation_agent.processor.review_queue import generate_candidate_clusters
from investigation_agent.agent import InvestigationTools, run_react
from investigation_agent.db.store import (
    get_cluster_evidence_ids,
    get_evidence_by_ids,
    get_evidence_by_target,
    list_candidate_clusters,
    list_evidence,
    list_evidence_by_review_status,
    list_incidents,
    merge_candidate_clusters,
    merge_classification_json,
    pipeline_counts,
    promote_candidate_cluster_to_incident,
    search_evidence_text,
    set_candidate_cluster_status,
    set_review_status,
    split_evidence_to_new_cluster,
    update_classification_json,
)
from investigation_agent.retrieval.chroma_store import index_evidence_safe, semantic_search as chroma_semantic_search
from investigation_agent.llm.json_util import parse_json_object
from investigation_agent.llm.ollama_client import OllamaChatError, chat_completion
from investigation_agent.llm.prompts import (
    CLASSIFY_SYSTEM,
    EXTRACT_SYSTEM,
    SUMMARIZE_SYSTEM,
    build_evidence_context,
    classify_user_prompt,
    extract_user_prompt,
    summarize_user_prompt,
)
from investigation_agent.processor.classifier import normalize_war_crimes_classifier
from investigation_agent.processor.extractor import facility_attack_relation, normalize_extraction_dict
from investigation_agent.workflows.ingest import perform_fetch

app = typer.Typer(
    help="Attack-focused evidence: Telegram + web search, relation-aware filter for attacks on civil facilities"
)
review_app = typer.Typer(help="Analyst review status for evidence rows")
candidates_app = typer.Typer(help="Candidate evidence bundles (heuristic matching; analyst review)")
incidents_app = typer.Typer(help="Reviewed incidents (promoted from candidates)")
scrape_app = typer.Typer(help="Targeted scraping (Telegram channel search)")
app.add_typer(review_app, name="review")
app.add_typer(candidates_app, name="candidates")
app.add_typer(incidents_app, name="incidents")
app.add_typer(scrape_app, name="scrape")
console = Console()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


@app.callback()
def main() -> None:
    init_db()


@app.command("fetch")
def cmd_fetch(
    target: Annotated[
        str,
        typer.Argument(help="Facility or place name; results are filtered to likely attack-related content"),
    ],
    lang: Annotated[str, typer.Option("--lang", "-l", help="Hint for web search: en or ar")] = "en",
    max_web: Annotated[
        int,
        typer.Option("--max-web", help="Max unique web URLs after bilingual SERP merge (AR+EN shared cap)"),
    ] = 15,
    web_date_filter: Annotated[
        str,
        typer.Option(
            "--web-date-filter",
            help="ddgs timelimit: none | week | month | year",
        ),
    ] = "none",
    web: Annotated[bool, typer.Option("--web/--no-web", help="Include web search")] = True,
    telegram: Annotated[bool, typer.Option("--telegram/--no-telegram", help="Search Telegram channels")] = True,
) -> None:
    """Search Telegram and the web; store only rows that pass the attack-on-civil-facility filter."""
    allowed_df = ("none", "week", "month", "year")
    wdf = web_date_filter.strip().lower()
    if wdf not in allowed_df:
        console.print(f"[red]--web-date-filter must be one of: {', '.join(allowed_df)}[/red]")
        raise typer.Exit(1)

    Session = get_session_factory()
    session = Session()
    try:
        stats = perform_fetch(
            session,
            target=target,
            lang=lang,
            max_web=max_web,
            web_date_filter=wdf,
            include_web=web,
            include_telegram=telegram,
        )
        run_id = stats["run_id"]
        added_tg = stats["added_tg"]
        dup_tg = stats["dup_tg"]
        filtered_tg = stats.get("filtered_tg_non_attack", 0)
        added_web = stats["added_web"]
        dup_web_url = stats["dup_web_url"]
        dup_web_hash = stats["dup_web_hash"]
        web_failed_status = stats["web_failed_status"]
        web_serp = stats["web_serp"]
        web_serp_ar = stats["web_serp_ar"]
        web_serp_en = stats["web_serp_en"]
        filtered_web = stats.get("filtered_web_non_attack", 0)
        if web and web_serp == 0:
            console.print(
                "[yellow]web_serp=0[/yellow]: no result rows after "
                "bilingual ddgs search + URL extraction. Try --max-web, check network, "
                "or use --no-web if Telegram is enough."
            )

        web_line = (
            f"  web: web_serp={web_serp if web else 0} "
            f"web_serp_ar={web_serp_ar if web else 0} "
            f"web_serp_en={web_serp_en if web else 0} "
            f"inserted={added_web} dedup_url={dup_web_url} dedup_body={dup_web_hash} "
            f"filtered_non_attack={filtered_web}"
        )
        console.print(
            f"[green]Done[/green] run_id={run_id} target={target!r}\n"
            f"  telegram: inserted={added_tg} deduped={dup_tg} filtered_non_attack={filtered_tg}\n"
            f"{web_line}"
        )
        if web_failed_status:
            parts = [f"{k}={v}" for k, v in sorted(web_failed_status.items())]
            console.print(f"  web inserted with non-ok status: {', '.join(parts)}")
    finally:
        session.close()


@scrape_app.command("telegram")
def cmd_scrape_telegram(
    target: Annotated[str, typer.Argument(help="Search string for Telethon channel search")],
    channel: Annotated[str, typer.Option("--channel", "-c", help="Single channel username (without @); overrides TELEGRAM_CHANNELS")],
    lang: Annotated[str, typer.Option("--lang", "-l", help="Recorded on search run")] = "en",
) -> None:
    """Search one Telegram channel for messages matching the target (no web)."""
    ch = channel.strip().lstrip("@")
    if not ch:
        console.print("[red]Provide --channel[/red]")
        raise typer.Exit(1)
    Session = get_session_factory()
    session = Session()
    try:
        stats = perform_fetch(
            session,
            target=target,
            lang=lang,
            max_web=15,
            web_date_filter="none",
            include_web=False,
            include_telegram=True,
            channels=[ch],
        )
        ft = stats.get("filtered_tg_non_attack", 0)
        console.print(
            f"[green]Done[/green] run_id={stats['run_id']} channel=@{ch} target={target!r}\n"
            f"  telegram: inserted={stats['added_tg']} deduped={stats['dup_tg']} filtered_non_attack={ft}"
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
    exclude_relation_negative: Annotated[
        bool,
        typer.Option(
            "--exclude-relation-negative/--no-exclude-relation-negative",
            help="Drop Chroma hits inferred as context-only or no attack on facility (default: on)",
        ),
    ] = True,
) -> None:
    """Search stored evidence by meaning (ChromaDB embeddings); optional relation-aware filtering."""
    inner_limit = min(limit * 5, 100) if target else limit
    hits = chroma_semantic_search(
        query, limit=inner_limit, exclude_relation_negative=exclude_relation_negative
    )
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
            rel = getattr(h, "facility_attack_relation", None) or "?"
            console.print(
                f"[bold]{h.evidence_id}[/bold] distance={dist:.4f} relation={rel} "
                f"{r.source_type} {r.source_url}",
                markup=False,
            )
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


@review_app.command("queue")
def cmd_review_queue(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max clusters to show")] = 30,
) -> None:
    """Show pending candidate clusters (same as: investigate candidates list --status pending)."""
    Session = get_session_factory()
    session = Session()
    try:
        rows = list_candidate_clusters(session, status="pending", limit=limit)
        if not rows:
            console.print("No pending candidate clusters.")
            return
        for c in rows:
            eids = get_cluster_evidence_ids(session, c.id)
            console.print(
                f"[bold]{c.id}[/bold] {c.status}  evidence_ids={eids}",
                markup=False,
            )
    finally:
        session.close()


@review_app.command("set")
def cmd_review_set(
    ids: Annotated[
        str,
        typer.Option(
            "--ids",
            help="Evidence ids: comma-separated and/or inclusive ranges, e.g. 58,60:75 or 50:110",
        ),
    ],
    status: Annotated[str, typer.Option("--status", help="pending | approved | rejected")],
) -> None:
    """Set review status for evidence rows."""
    if status not in ("pending", "approved", "rejected"):
        console.print("[red]status must be pending, approved, or rejected[/red]")
        raise typer.Exit(1)
    id_list = _parse_id_list_cli(ids)
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


@candidates_app.command("generate")
def cmd_candidates_generate(
    evidence_limit: Annotated[int, typer.Option("--evidence-limit", help="Recent evidence rows to scan")] = 200,
    min_score: Annotated[float, typer.Option("--min-score", help="Minimum pair score to create a cluster")] = 0.45,
) -> None:
    """Create pending candidate clusters from heuristic pair scores (conservative)."""
    Session = get_session_factory()
    session = Session()
    try:
        n = generate_candidate_clusters(session, evidence_limit=evidence_limit, min_score=min_score)
        session.commit()
        console.print(f"[green]Created[/green] {n} candidate cluster(s).")
    finally:
        session.close()


@candidates_app.command("list")
def cmd_candidates_list(
    status: Annotated[
        str | None,
        typer.Option("--status", help="pending | approved | rejected | merged"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 30,
) -> None:
    """List candidate clusters with evidence ids."""
    Session = get_session_factory()
    session = Session()
    try:
        rows = list_candidate_clusters(session, status=status, limit=limit)
        if not rows:
            console.print("No candidate clusters. Run [bold]investigate candidates generate[/bold]")
            return
        for c in rows:
            eids = get_cluster_evidence_ids(session, c.id)
            console.print(
                f"[bold]{c.id}[/bold] {c.status}  evidence_ids={eids}"
                + (f"  note={c.reviewer_note!r}" if c.reviewer_note else ""),
                markup=False,
            )
    finally:
        session.close()


@candidates_app.command("approve")
def cmd_candidates_approve(
    cluster_id: Annotated[int, typer.Option("--id", help="Candidate cluster id")],
    note: Annotated[str | None, typer.Option("--note")] = None,
) -> None:
    Session = get_session_factory()
    session = Session()
    try:
        row = set_candidate_cluster_status(session, cluster_id, "approved", reviewer_note=note)
        if row is None:
            console.print("[red]Cluster not found[/red]")
            raise typer.Exit(1)
        session.commit()
        console.print(f"[green]Cluster {cluster_id} approved[/green]")
    finally:
        session.close()


@candidates_app.command("reject")
def cmd_candidates_reject(
    cluster_id: Annotated[int, typer.Option("--id", help="Candidate cluster id")],
    note: Annotated[str | None, typer.Option("--note")] = None,
) -> None:
    Session = get_session_factory()
    session = Session()
    try:
        row = set_candidate_cluster_status(session, cluster_id, "rejected", reviewer_note=note)
        if row is None:
            console.print("[red]Cluster not found[/red]")
            raise typer.Exit(1)
        session.commit()
        console.print(f"[yellow]Cluster {cluster_id} rejected[/yellow]")
    finally:
        session.close()


@candidates_app.command("merge")
def cmd_candidates_merge(
    into: Annotated[int, typer.Option("--into", help="Cluster id to keep")],
    merge_from: Annotated[int, typer.Option("--from", help="Cluster id to merge into --into and remove")],
) -> None:
    Session = get_session_factory()
    session = Session()
    try:
        ok = merge_candidate_clusters(session, keep_id=into, merge_id=merge_from)
        if not ok:
            console.print("[red]Merge failed (ids missing or invalid)[/red]")
            raise typer.Exit(1)
        session.commit()
        console.print(f"[green]Merged cluster {merge_from} into {into}[/green]")
    finally:
        session.close()


@candidates_app.command("split")
def cmd_candidates_split(
    cluster_id: Annotated[int, typer.Option("--cluster", help="Source cluster id")],
    evidence_id: Annotated[int, typer.Option("--evidence-id", help="Evidence row to move to a new cluster")],
) -> None:
    Session = get_session_factory()
    session = Session()
    try:
        new_c = split_evidence_to_new_cluster(session, from_cluster_id=cluster_id, evidence_id=evidence_id)
        if new_c is None:
            console.print("[red]Split failed (link not found)[/red]")
            raise typer.Exit(1)
        session.commit()
        console.print(f"[green]Created cluster {new_c.id} with evidence {evidence_id}[/green]")
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
    """
    Parse evidence id lists from CLI ``--ids``.

    Supports comma-separated ids and inclusive ranges ``start:end`` (``start <= end``).
    Order is preserved; duplicates are dropped on first occurrence.
    """
    if not ids_str or not ids_str.strip():
        return []
    seen: set[int] = set()
    out: list[int] = []
    for part in ids_str.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            pieces = part.split(":")
            if len(pieces) != 2:
                raise ValueError(f"invalid range token: {part!r}")
            left, right = pieces[0].strip(), pieces[1].strip()
            if not left or not right:
                raise ValueError(f"invalid range token: {part!r}")
            try:
                start = int(left)
                end = int(right)
            except ValueError as e:
                raise ValueError(f"invalid range token: {part!r}") from e
            if start > end:
                raise ValueError(f"invalid range token: {part!r}; start must be <= end")
            for i in range(start, end + 1):
                if i not in seen:
                    seen.add(i)
                    out.append(i)
        else:
            try:
                i = int(part)
            except ValueError as e:
                raise ValueError(f"invalid id token: {part!r}") from e
            if i not in seen:
                seen.add(i)
                out.append(i)
    return out


def _parse_id_list_cli(ids_str: str | None) -> list[int]:
    try:
        return _parse_id_list(ids_str)
    except ValueError as e:
        console.print(f"[red]Invalid --ids:[/red] {e}")
        raise typer.Exit(1)


@app.command("summarize")
def cmd_summarize(
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Filter evidence by target substring"),
    ] = None,
    ids: Annotated[
        str | None,
        typer.Option(
            "--ids",
            help="Evidence ids: comma-separated and/or inclusive ranges, e.g. 58,55 or 60:75",
        ),
    ] = None,
    cluster_id: Annotated[
        int | None,
        typer.Option("--cluster-id", help="Summarize evidence linked to one candidate cluster"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows when using --target")] = 8,
    approved_only: Annotated[
        bool,
        typer.Option("--approved-only", help="Only include approved evidence (excludes pending and rejected)"),
    ] = False,
) -> None:
    """Summarize stored evidence with citation tags and source list (local Ollama)."""
    id_list = _parse_id_list_cli(ids) if ids else []
    selectors = int(bool(id_list)) + int(bool(target)) + int(cluster_id is not None)
    if selectors == 0:
        console.print("[red]Provide one of --target, --ids, or --cluster-id[/red]")
        raise typer.Exit(1)
    if selectors > 1:
        console.print("[red]Use only one of --target, --ids, or --cluster-id[/red]")
        raise typer.Exit(1)

    Session = get_session_factory()
    session = Session()
    try:
        if cluster_id is not None:
            cluster_ids = get_cluster_evidence_ids(session, cluster_id)
            if not cluster_ids:
                console.print(f"[yellow]No evidence linked to cluster {cluster_id}.[/yellow]")
                raise typer.Exit(0)
            id_list = cluster_ids

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
        typer.Option(
            "--ids",
            help="Evidence ids: comma-separated and/or inclusive ranges, e.g. 58,55 or 50:110",
        ),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows when using --target")] = 20,
) -> None:
    """Extract attack-on-civil-facility fields per row; merge JSON into classification_json (Ollama)."""
    id_list = _parse_id_list_cli(ids) if ids else []
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
                data = normalize_extraction_dict(data)
                merge_classification_json(session, r.id, data)
                session.commit()
                console.print(
                    f"[green]ok[/green] id={r.id} attack_occurred={data.get('attack_occurred')!r} "
                    f"attack_type={data.get('attack_type')!r} facility_type={data.get('facility_type')!r} "
                    f"facility_attack_relation={data.get('facility_attack_relation')!r} "
                    f"facility_target_object={data.get('facility_target_object')!r}"
                )
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


@app.command("classify")
def cmd_classify(
    target: Annotated[
        str | None,
        typer.Option("--target", "-t", help="Filter evidence by target substring"),
    ] = None,
    ids: Annotated[
        str | None,
        typer.Option(
            "--ids",
            help="Evidence ids: comma-separated and/or inclusive ranges, e.g. 58,55 or 50:110",
        ),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max rows when using --target")] = 20,
) -> None:
    """War-crimes triage + civil-facility attack relevance (Ollama); merges into classification_json.war_crimes_classifier."""
    id_list = _parse_id_list_cli(ids) if ids else []
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
            console.print("No evidence to classify.")
            raise typer.Exit(0)

        for r in rows:
            user = classify_user_prompt(r.id, r.source_url, r.source_type, r.raw_text or "")
            llm_raw = ""
            try:
                llm_raw = chat_completion(
                    [
                        {"role": "system", "content": CLASSIFY_SYSTEM},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.1,
                )
                data = parse_json_object(llm_raw)
                normalized = normalize_war_crimes_classifier(data)
                merge_classification_json(session, r.id, {"war_crimes_classifier": normalized})
                session.commit()
                console.print(
                    f"[green]ok[/green] id={r.id} is_genocidal={normalized.get('is_genocidal')!r} "
                    f"overall={normalized.get('overall_confidence')} "
                    f"facility_attack_relation={normalized.get('facility_attack_relation')!r}"
                )
            except OllamaChatError as e:
                console.print(f"[red]id={r.id} Ollama:[/red] {e}")
                merge_classification_json(
                    session,
                    r.id,
                    {"war_crimes_classifier": {"error": "ollama", "message": str(e)}},
                )
                session.commit()
            except ValueError as e:
                console.print(f"[yellow]id={r.id} parse:[/yellow] {e}")
                merge_classification_json(
                    session,
                    r.id,
                    {
                        "war_crimes_classifier": {
                            "error": "parse_failed",
                            "message": str(e),
                            "raw": (llm_raw or "")[:2000],
                        }
                    },
                )
                session.commit()
    finally:
        session.close()


@app.command("query")
def cmd_query(
    query_text: Annotated[str, typer.Argument(help="Question or topic; used for local search and optional fetch")],
    target: Annotated[
        Optional[str],
        typer.Option("--target", "-t", help="Only evidence whose target_query contains this substring"),
    ] = None,
    fetch_threshold: Annotated[int, typer.Option("--fetch-threshold", help="Min local hits before skipping fetch")] = 3,
    local_only: Annotated[bool, typer.Option("--local-only", help="Do not run Telegram/web fetch")] = False,
    auto_fetch: Annotated[
        bool,
        typer.Option("--auto-fetch-on-miss/--no-auto-fetch-on-miss", help="Fetch when local hits are below threshold"),
    ] = True,
    lang: Annotated[str, typer.Option("--lang", "-l")] = "en",
    max_web: Annotated[int, typer.Option("--max-web")] = 15,
    web_date_filter: Annotated[str, typer.Option("--web-date-filter")] = "none",
    web: Annotated[bool, typer.Option("--web/--no-web")] = True,
    telegram: Annotated[bool, typer.Option("--telegram/--no-telegram")] = True,
) -> None:
    """Local-first: semantic + substring search (relation-aware Chroma filter); optionally fetch, then summarize (Ollama)."""
    allowed_df = ("none", "week", "month", "year")
    wdf = web_date_filter.strip().lower()
    if wdf not in allowed_df:
        console.print(f"[red]--web-date-filter must be one of: {', '.join(allowed_df)}[/red]")
        raise typer.Exit(1)

    Session = get_session_factory()
    session = Session()
    try:

        def _collect_ids() -> list[int]:
            seen: set[int] = set()
            out: list[int] = []
            for h in chroma_semantic_search(query_text, limit=80):
                r = session.get(Evidence, h.evidence_id)
                if r is None:
                    continue
                if target and target.lower() not in (r.target_query or "").lower():
                    continue
                if h.evidence_id not in seen:
                    seen.add(h.evidence_id)
                    out.append(h.evidence_id)
            for r in search_evidence_text(session, query=query_text, target_substring=target, limit=40):
                if r.id not in seen:
                    seen.add(r.id)
                    out.append(r.id)
            return out

        ids = _collect_ids()
        fetched = False
        if len(ids) < fetch_threshold and not local_only and auto_fetch:
            console.print(
                f"[yellow]Local hits={len(ids)} < threshold={fetch_threshold}[/yellow] — running fetch…"
            )
            fetch_stats = perform_fetch(
                session,
                target=query_text,
                lang=lang,
                max_web=max_web,
                web_date_filter=wdf,
                include_web=web,
                include_telegram=telegram,
            )
            fetched = True
            console.print(
                "[dim]fetch ingest filter: "
                f"tg_non_attack={fetch_stats.get('filtered_tg_non_attack', 0)} "
                f"web_non_attack={fetch_stats.get('filtered_web_non_attack', 0)}[/dim]"
            )
            ids = _collect_ids()

        if not ids:
            console.print("No evidence found locally" + (" after fetch." if fetched else "."))
            raise typer.Exit(0)

        rows = get_evidence_by_ids(session, ids[: max(15, fetch_threshold)])
        n_inc = len(list_incidents(session, status=None, limit=50))
        n_cand = len(list_candidate_clusters(session, status="pending", limit=20))
        rel_counts = Counter()
        for r in rows[:12]:
            rel = facility_attack_relation(r) or "unknown"
            rel_counts[rel] += 1
        console.print(
            f"[dim]local_evidence_used={len(rows)} incidents_in_db={n_inc} pending_clusters_shown_cap={n_cand} "
            f"fetched={fetched} facility_attack_relation_counts={dict(rel_counts)}[/dim]"
        )
        ctx = build_evidence_context(rows[:12])
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
        console.print("\n[bold]Sources[/bold]")
        for r in rows[:12]:
            console.print(f"  id={r.id}  {r.source_url}", markup=False)
    finally:
        session.close()


@incidents_app.command("list")
def cmd_incidents_list(
    status: Annotated[
        str | None,
        typer.Option("--status", help="candidate | reviewed | confirmed | rejected"),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 30,
) -> None:
    """List reviewed incidents."""
    Session = get_session_factory()
    session = Session()
    try:
        rows = list_incidents(session, status=status, limit=limit)
        if not rows:
            console.print("No incidents. Approve a candidate cluster then: [bold]investigate incidents promote --cluster-id ID[/bold]")
            return
        for r in rows:
            console.print(
                f"[bold]{r.id}[/bold] {r.status}  {r.title or ''}  cluster={r.source_cluster_id}",
                markup=False,
            )
    finally:
        session.close()


@incidents_app.command("promote")
def cmd_incidents_promote(
    cluster_id: Annotated[int, typer.Option("--cluster-id", help="Must be an approved candidate cluster")],
) -> None:
    """Promote an approved candidate cluster to a reviewed incident (idempotent)."""
    Session = get_session_factory()
    session = Session()
    try:
        try:
            inc = promote_candidate_cluster_to_incident(session, cluster_id)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        if inc is None:
            console.print("[red]Promotion failed: cluster missing, not approved, or no evidence links.[/red]")
            raise typer.Exit(1)
        session.commit()
        console.print(f"[green]Incident[/green] id={inc.id}  title={inc.title!r}")
    finally:
        session.close()


@app.command("ask")
def cmd_ask(
    question: Annotated[str, typer.Argument(help="Question; uses tools + local Ollama")],
) -> None:
    """Conservative assistant over stored evidence (tools + ReAct)."""
    Session = get_session_factory()
    session = Session()
    try:
        tools = InvestigationTools(session)
        out = run_react(tools, question)
        console.print(out, markup=False)
    finally:
        session.close()


@app.command("report")
def cmd_report(
    incident_id: Annotated[int, typer.Argument(help="Incident id from investigate incidents list")],
) -> None:
    """Print a conservative text report for one incident (linked evidence previews)."""
    Session = get_session_factory()
    session = Session()
    try:
        tools = InvestigationTools(session)
        raw = tools.tool_generate_report(incident_id)
        data = json.loads(raw)
        if "error" in data:
            console.print(f"[red]{data['error']}[/red]")
            raise typer.Exit(1)
        console.print(data.get("report", ""), markup=False)
    finally:
        session.close()


@app.command("status")
def cmd_status() -> None:
    """Show rough pipeline counts (evidence, runs, clusters, incidents)."""
    Session = get_session_factory()
    session = Session()
    try:
        c = pipeline_counts(session)
        console.print(
            f"evidence_rows={c['evidence_rows']}  search_runs={c['search_runs']}  "
            f"candidate_clusters={c['candidate_clusters']}  incidents={c['incidents']}  "
            f"evidence_pending_review={c['evidence_pending_review']}"
        )
    finally:
        session.close()


if __name__ == "__main__":
    app()
