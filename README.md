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

`investigate fetch` prints ingestion stats: Telegram inserted vs deduped, **`web_serp=N`** (total unique URLs after bilingual SERP merge and before fetch), **`web_serp_ar`** / **`web_serp_en`** (how many of those URLs came from the Arabic vs English SERP pass; same URL in both counts once, Arabic wins), web inserted vs URL/body-hash dedupes, and counts of inserted rows whose fetch status was not `ok`. **`--max-web`** is a **shared cap** across Arabic + English (merged list, deduped by normalized URL). Web search uses the **[`ddgs`](https://pypi.org/project/ddgs/)** package (DuckDuckGo-style text search). If **`web_serp=0`**, the CLI prints a yellow hint: empty SERP, blocking, or network issues — try again, increase `--max-web`, set **`DDGS_PROXY`** if you need a proxy, or use **`--no-web`** to skip web.

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

# Structured extraction per row (JSON stored in DB column classification_json)
investigate extract --target "مجمع الشفاء الطبي" --limit 10

investigate extract --ids 58,55
```

Extraction is analyst aid only — verify against sources.

## Data

By default the database is `./data/investigation.db` (created automatically).

Main tables:

- **`search_runs`** — one row per `investigate fetch` invocation (target, language, flags).
- **`search_results`** — one row per web SERP hit for that run (rank, URL, snippet, engine `ddgs`, language, fetch status, optional error detail). Linked from **`evidence`** via `search_result_id` when a row was ingested from web.
- **`sources`** — optional registered origins (e.g. web domain) for provenance.
- **`evidence`** — stored items with `normalized_url` for deduplication, `content_hash`, and analyst **`review_status`**.
- **`candidate_clusters`** / **`candidate_evidence_links`** — heuristic groupings for manual review (scores and textual **reasons** on each link).

Run tests (dev): `pip install -e ".[dev]"` then `pytest`.

## License

Private / your use case — add a license if you publish the repo.
