# Investigation Agent

Collect evidence for a **named target** (e.g. a hospital or school) by:

- Searching configured **Telegram channels** for messages matching the target (not full-channel dumps).
- Running a **bilingual (Arabic + English) keyword web search** and extracting article text.

Everything is stored in **SQLite** with source URLs for manual review.

## Setup

```bash
cd investigation-agent
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp config/.env.example config/.env
# Edit config/.env with TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, TELEGRAM_CHANNELS
```

Environment files are loaded in order (later overrides earlier): `config/.env`, then `.env` at the project root, then `.env` in the current working directory.

First Telegram login will prompt for a code in the terminal and create `investigation_agent_session.session` in the project directory. To reuse an existing Telethon session from another project (same API ID/hash), copy that `.session` file to `investigation_agent_session.session` here.

## Usage

```bash
# Fetch Telegram + web for a target (default: both)
investigate fetch "Al Shifa Hospital"

# Arabic target, web only
investigate fetch "مستشفى الشفاء" --lang ar --no-telegram

# Optional: restrict web SERP by recency (ddgs timelimit: week | month | year)
investigate fetch "hospital Khan Younis" --web-date-filter month --max-web 20

# List stored evidence (optionally filter by target substring)
investigate list --target "Shifa"

# Search within stored evidence text
investigate search "emergency" --target "Shifa"

# Semantic search (ChromaDB embeddings; new fetches index automatically)
investigate reindex
investigate semantic-search "hospital fuel generators" --target "مجمع" --limit 10

# Analyst review (pending | approved | rejected)
investigate review list --status pending
investigate review set --ids 58,56 --status approved

# Summarize only approved rows
investigate summarize --target "مجمع" --limit 8 --approved-only
```

`investigate fetch` prints ingestion stats: Telegram inserted vs deduped, **`web_serp=N`** (total unique URLs after bilingual SERP merge and before fetch), **`web_serp_ar`** / **`web_serp_en`** (how many of those URLs came from the Arabic vs English SERP pass; same URL in both counts once, Arabic wins), web inserted vs URL/body-hash dedupes, and counts of inserted rows whose fetch status was not `ok`. **`--max-web`** is a **shared cap** across Arabic + English (merged list, deduped by normalized URL). Use **`--web-date-filter`** (`none` \| `week` \| `month` \| `year`) to pass a ddgs **timelimit** on both SERP passes; the run stores this on **`search_runs.web_date_filter`**, and each **`search_results`** row stores **`serp_region`**, **`serp_pass`** (`ar` \| `en`), and **`date_filter_applied`**. Web search uses the **[`ddgs`](https://pypi.org/project/ddgs/)** package. If **`web_serp=0`**, the CLI prints a yellow hint: empty SERP, blocking, or network issues — try again, increase `--max-web`, set **`DDGS_PROXY`** if you need a proxy, or use **`--no-web`** to skip web.

### Candidate clusters (heuristic matching)

After you have evidence (and optionally `investigate extract` for richer `classification_json`), you can generate **pending** candidate bundles for analyst review. Nothing is auto-confirmed.

```bash
investigate candidates generate --evidence-limit 200 --min-score 0.45
investigate candidates list --status pending
investigate candidates approve --id 1
investigate candidates reject --id 2 --note "different incident"
investigate candidates merge --into 1 --from 3
investigate candidates split --cluster 1 --evidence-id 42
```

### Incidents (promoted bundles)

After you **approve** a candidate cluster, promote it to an audited **incident** (idempotent). Then list incidents or print a conservative text report.

```bash
investigate candidates approve --id 1
investigate incidents promote --cluster-id 1
investigate incidents list
investigate report 1
```

### Assistant and pipeline status (local Ollama)

Requires Ollama running (`ollama serve`). `ask` uses a small ReAct loop with read-only tools over your DB (search evidence, list incidents, cross-reference, summarize, generate report text).

```bash
investigate status
investigate ask "What evidence mentions schools in Rafah?"
```

ChromaDB files live under `./data/chroma` by default. Override with `CHROMA_PERSIST_DIR` in `config/.env`.

**First run:** The default embedding model (~80MB ONNX) is downloaded once to your Chroma cache (e.g. `~/.cache/chroma/`). The first `reindex` or `semantic-search` after install may take a minute while that completes.

## Local LLM (Ollama)

Install [Ollama](https://ollama.com/) and pull the default model used by this project:

```bash
ollama pull qwen2.5:3b-instruct
```

Configure in `config/.env`:

- `OLLAMA_BASE_URL` (default `http://localhost:11434`)
- `OLLAMA_MODEL` (must match a model you have pulled)
- `OLLAMA_TIMEOUT_SECONDS`

Then:

```bash
# Summarize a batch (asks model for citation-style bullets; always lists batch URLs)
investigate summarize --target "مجمع الشفاء الطبي" --limit 8

investigate summarize --ids 58,56

# Structured extraction per row (JSON merged into classification_json top-level keys)
investigate extract --target "مجمع الشفاء الطبي" --limit 10

investigate extract --ids 58,55

# 9-flag war-crimes triage (separate schema; stored under classification_json.war_crimes_classifier)
investigate classify --target "مجمع" --limit 5
investigate classify --ids 58,55
```

**Extraction vs classification:** `extract` fills facility/location/casualties-style fields. `classify` fills the legacy-compatible **nine boolean signals** plus per-flag confidence and explanation (see Telescraper-style flags in code). Both merge into `classification_json` without wiping the other block.

### Local-first query (semantic + substring, optional fetch)

Searches **Chroma** (semantic) and **SQLite** (substring), then summarizes with Ollama. If local hits are below `--fetch-threshold`, runs a normal **`fetch`** (unless `--local-only` or `--no-auto-fetch-on-miss`).

```bash
investigate query "hospital strike Gaza" --fetch-threshold 3
investigate query "مستشفى" --target "غزة" --local-only
```

### Telegram-only scrape (single channel)

```bash
investigate scrape telegram "search phrase" --channel mychannel
```

### Review queue alias

```bash
investigate review queue
# same idea as: investigate candidates list --status pending
```

Extraction and classification are analyst aids only — verify against sources.

### Residual risks

- **Web fetch:** many news sites return 403 or fail DNS; you still store the SERP row with non-ok fetch status.
- **Large DBs:** `candidates generate` can create many clusters; tune `--evidence-limit`, `--min-score`, and promote only after review.
- **Ollama:** `query`, `classify`, `extract`, `summarize`, `ask` need a running model (`ollama serve`).

### Evaluation smoke

```bash
./scripts/smoke_eval.sh
# optional LLM touch (needs Ollama):
RUN_LLM=1 ./scripts/smoke_eval.sh
```

## Data

By default the database is `./data/investigation.db` (created automatically).

Main tables:

- **`search_runs`** — one row per `investigate fetch` invocation (target, language, flags, **`web_date_filter`**).
- **`search_results`** — one row per web SERP hit for that run (rank, URL, snippet, engine `ddgs`, language, **`serp_region`**, **`serp_pass`**, **`date_filter_applied`**, fetch status, optional error detail). Linked from **`evidence`** via `search_result_id` when a row was ingested from web.
- **`sources`** — optional registered origins (e.g. web domain) for provenance.
- **`evidence`** — stored items with `normalized_url` for deduplication, `content_hash`, and analyst **`review_status`**.
- **`candidate_clusters`** / **`candidate_evidence_links`** — heuristic groupings for manual review (scores and textual **reasons** on each link).
- **`incidents`** / **`incident_evidence`** — analyst-reviewed incident bundles promoted from approved clusters (or extended later for manual linking).

**Smoke workflow:** `investigate fetch "..."` → `investigate extract --target "..." --limit 5` → `investigate candidates generate` → `investigate candidates approve --id N` → `investigate incidents promote --cluster-id N` → `investigate report <incident_id>`.

Run tests (dev): `pip install -e ".[dev]"` then `pytest`.

## License

Private / your use case — add a license if you publish the repo.
