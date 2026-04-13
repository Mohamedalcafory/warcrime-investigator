# Investigation Agent

Collect and triage evidence about **attacks on civil facilities** (hospitals, schools, shelters, places of worship, etc.) for a **named target**.

**Sources**

- Configured **Telegram** channels (search by target; not full-channel dumps).
- **Bilingual web search** (Arabic + English) with article text extraction.

**Storage**

Everything that passes the ingest filter is stored in **SQLite** with source URLs for manual review.

---

## Contents

- [How ingestion filters work](#how-ingestion-filters-work)
- [Setup](#setup)
- [Usage](#usage)
- [Fetch output (what the numbers mean)](#fetch-output-what-the-numbers-mean)
- [Candidate clusters & incidents](#candidate-clusters--incidents)
- [Local LLM (Ollama)](#local-llm-ollama)
- [Query, extract, classify](#query-extract-classify)
- [Command reference](#command-reference)
- [Data model](#data-model)
- [License](#license)

---

## How ingestion filters work

Ingestion is **relation-aware**, not just “facility word + attack word” in the same text. Deterministic rules decide whether violence is plausibly tied to a civil facility.

| Kept (examples) | Dropped (examples) |
|-----------------|-------------------|
| **Direct hit** on the site | **Context-only** (e.g. hospital director discussing strikes elsewhere with no attack on the site) |
| **Inside the compound** | **No attack on a civil facility** |
| **Nearby / adjacent** violence | |
| **Associated asset** (ambulance, gate, staff/patients in a facility-linked incident) | |

Structured fields **`facility_attack_relation`** and **`facility_target_object`** (from `extract` / `classify`) use the same idea. To tune behavior, edit patterns in `investigation_agent/processor/attack_filter.py` (`infer_facility_attack_relation`).

---

## Setup

```bash
cd investigation-agent
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp config/.env.example config/.env
# Edit config/.env: TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, TELEGRAM_CHANNELS
```

**Environment load order** (later overrides earlier): `config/.env` → `.env` at repo root → `.env` in the current working directory.

**Telegram session:** First login prompts for a code and creates `investigation_agent_session.session` in the project directory. To reuse a Telethon session from another project (same API ID/hash), copy that `.session` file to `investigation_agent_session.session` here.

---

## Usage

### Fetch, list, search

```bash
# Telegram + web (default). Rows that fail the ingest filter count as filtered.
investigate fetch "Al Shifa Hospital"

# Arabic target, web only
investigate fetch "مستشفى الشفاء" --lang ar --no-telegram

# Web SERP recency: week | month | year (ddgs timelimit)
investigate fetch "hospital Khan Younis" --web-date-filter month --max-web 20

# List / search stored evidence
investigate list --target "Shifa"
investigate search "emergency" --target "Shifa"
```

### Semantic search (Chroma)

New fetches index into Chroma automatically. For older DBs, run **`reindex`** once.

By default, semantic hits that look like **context-only** or **no attack on the facility** are dropped. To see all embedding neighbors:

```bash
investigate semantic-search "your query" --no-exclude-relation-negative
```

Indexed rows include **`facility_attack_relation`** metadata.

```bash
investigate reindex
investigate semantic-search "hospital fuel generators" --target "مجمع" --limit 10
```

### Review workflow

```bash
investigate review list --status pending
investigate review set --ids 58,56 --status approved
# Inclusive range = every id from 50 through 110
investigate review set --ids 50:110 --status approved

investigate summarize --target "مجمع" --limit 8 --approved-only
```

---

## Fetch output (what the numbers mean)

`investigate fetch` prints ingestion stats. Main ideas:

- **Telegram:** inserted vs deduplicated vs **`filtered_non_attack`** (skipped by the civil-facility attack filter).
- **Web:** **`web_serp`** = unique URLs after bilingual SERP merge and before fetch. **`web_serp_ar`** / **`web_serp_en`** = how many URLs came from the Arabic vs English pass (same URL in both counts once; Arabic wins).
- **Web:** inserted vs URL dedupe vs body-hash dedupe vs **`filtered_non_attack`**, plus counts of rows whose fetch status was not `ok`.

**`--max-web`** is a **single cap** shared across Arabic + English (merged list, deduped by normalized URL).

**`--web-date-filter`** (`none` \| `week` \| `month` \| `year`) sets a ddgs **timelimit** on both SERP passes. The run stores this on **`search_runs.web_date_filter`**. Each **`search_results`** row can store **`serp_region`**, **`serp_pass`** (`ar` \| `en`), and **`date_filter_applied`**.

Web search uses the **[ddgs](https://pypi.org/project/ddgs/)** package. If **`web_serp=0`**, the CLI may hint: empty SERP, blocking, or network issues — retry, raise **`--max-web`**, set **`DDGS_PROXY`** if needed, or use **`--no-web`**.

---

## Candidate clusters & incidents

### Candidate clusters (heuristic matching)

After you have evidence (optionally run **`investigate extract`** for richer `classification_json`), generate **pending** bundles for review. Nothing is auto-confirmed.

```bash
investigate candidates generate --evidence-limit 200 --min-score 0.45
investigate candidates list --status pending
investigate candidates approve --id 1
investigate candidates reject --id 2 --note "different incident"
investigate candidates merge --into 1 --from 3
investigate candidates split --cluster 1 --evidence-id 42
```

**Matching:** `candidates generate` prefers compatible **`facility_attack_relation`** pairs and penalizes rows that are **`facility_used_as_context_only`** when relation fields exist in `classification_json`.

### Incidents (promoted bundles)

Approve a cluster, then promote to an **incident** (idempotent). List incidents or print a report.

```bash
investigate candidates approve --id 1
investigate incidents promote --cluster-id 1
investigate incidents list
investigate report 1
```

### Assistant (`ask`) and status

Requires Ollama (`ollama serve`). `ask` runs a small ReAct loop with read-only tools over your DB.

```bash
investigate status
investigate ask "What evidence mentions schools in Rafah?"
```

**Chroma:** default path `./data/chroma`. Override with **`CHROMA_PERSIST_DIR`** in `config/.env`.

**First run:** The default embedding model (~80MB ONNX) downloads once (e.g. under `~/.cache/chroma/`). The first `reindex` or `semantic-search` may take a minute.

---

## Local LLM (Ollama)

Install [Ollama](https://ollama.com/) and pull the project default model:

```bash
ollama pull qwen2.5:3b-instruct
```

Set in `config/.env`:

| Variable | Notes |
|----------|--------|
| `OLLAMA_BASE_URL` | Default `http://localhost:11434` |
| `OLLAMA_MODEL` | Must match a model you have pulled |
| `OLLAMA_TIMEOUT_SECONDS` | |

---

## Query, extract, classify

### Summarize, extract, classify

```bash
investigate summarize --target "مجمع الشفاء الطبي" --limit 8
investigate summarize --ids 58,56
investigate summarize --ids 60:75
investigate summarize --cluster-id 1

investigate extract --target "مجمع الشفاء الطبي" --limit 10
investigate extract --ids 58,55

investigate classify --target "مجمع" --limit 5
investigate classify --ids 58,55
```

**Extract** merges JSON into `classification_json` (top-level keys): facility/location/casualties-style fields plus **`facility_attack_relation`**, **`facility_target_object`**, **`facility_attack_relation_confidence`**.

**Classify** merges into **`classification_json.war_crimes_classifier`**: nine boolean signals, per-flag confidence, **`facility_attack_relation`** / **`facility_attack_relation_confidence`**, civil-facility relevance, explanation. The two commands **do not wipe each other’s blocks**.

Extraction and classification are **aids only** — verify against sources.

### Local-first `query`

Combines **Chroma** (semantic; relation-aware filtering on by default) and **SQLite** (substring), then summarizes with Ollama. The CLI prints **`facility_attack_relation_counts`** for rows used in the summary. If local hits fall below **`--fetch-threshold`**, runs **`fetch`** unless **`--local-only`** or **`--no-auto-fetch-on-miss`**.

```bash
investigate query "hospital strike Gaza" --fetch-threshold 3
investigate query "مستشفى" --target "غزة" --local-only
```

### Other commands

```bash
investigate scrape telegram "search phrase" --channel mychannel
investigate review queue   # same idea as: investigate candidates list --status pending
```

### Residual risks

- **Web fetch:** Many sites return 403 or fail DNS; SERP rows may be stored with non-ok fetch status.
- **Large DBs:** `candidates generate` can create many clusters — tune `--evidence-limit` and `--min-score`.
- **Ollama:** `query`, `classify`, `extract`, `summarize`, and `ask` need a running model.

### Evaluation smoke

```bash
./scripts/smoke_eval.sh
RUN_LLM=1 ./scripts/smoke_eval.sh   # optional; needs Ollama
```

---

## Command reference

Run **`investigate --help`** for live help. The CLI is **attack-focused**: ingest uses facility attack relations; LLM commands target **violence against civil facilities**, not generic facility news.

### Top-level commands

| Command | Purpose |
|---------|---------|
| `fetch` | Ingest Telegram + web for a target |
| `list` | List stored evidence |
| `search` | Substring search (SQLite) |
| `semantic-search` | Semantic search (Chroma) |
| `reindex` | Rebuild Chroma from SQLite |
| `summarize` | Summarize evidence (Ollama) |
| `extract` | Structured extraction → `classification_json` (Ollama) |
| `classify` | War-crimes triage → `war_crimes_classifier` (Ollama) |
| `query` | Local search + optional fetch + summarize |
| `ask` | ReAct assistant over stored evidence |
| `report` | Text report for one incident |
| `status` | Pipeline counts |
| `review`, `candidates`, `incidents`, `scrape` | Subcommand groups |

### Common examples

```bash
# Ingest
investigate fetch "Al Shifa Hospital" --max-web 15 --web-date-filter month
investigate scrape telegram "Al Shifa Hospital" --channel mychannel

# Retrieval
investigate list --target "Shifa" --limit 50
investigate search "emergency" --target "Shifa" --limit 30
investigate semantic-search "hospital fuel generators" --target "مجمع" --limit 15
investigate reindex --limit 2000

# Review
investigate review list --status pending --limit 50
investigate review set --ids 58,60:75 --status approved
investigate review queue --limit 30

# Candidates & incidents
investigate candidates generate --evidence-limit 200 --min-score 0.45
investigate candidates list --status pending --limit 30
investigate candidates approve --id 1
investigate candidates reject --id 2 --note "different incident"
investigate candidates merge --into 1 --from 3
investigate candidates split --cluster 1 --evidence-id 42
investigate incidents promote --cluster-id 1
investigate incidents list --status reviewed --limit 30
investigate report 1

# LLM (Ollama required)
investigate summarize --target "مجمع الشفاء الطبي" --limit 8
investigate summarize --ids 58,60:75
investigate summarize --cluster-id 1
investigate extract --ids 58,60:75
investigate classify --ids 58,60:75
investigate ask "What evidence mentions schools in Rafah?"
investigate query "hospital strike Gaza" --fetch-threshold 3 --auto-fetch-on-miss
```

### `--ids` format

Used by `review set`, `summarize`, `extract`, and `classify`.

- Comma-separated ids and **inclusive ranges**.
- Examples: `58,59,60` · `50:110` · `10,12:15,20`

---

## Data model

Default database: **`./data/investigation.db`** (created automatically).

| Table | Role |
|-------|------|
| **`search_runs`** | One row per `fetch` (target, language, flags, **`web_date_filter`**) |
| **`search_results`** | One row per web SERP hit (rank, URL, snippet, **`serp_region`**, **`serp_pass`**, **`date_filter_applied`**, fetch status). Linked from **`evidence`** via `search_result_id` when ingested from web |
| **`sources`** | Optional origins (e.g. web domain) |
| **`evidence`** | Stored items; `normalized_url`, `content_hash`, **`review_status`** |
| **`candidate_clusters`** / **`candidate_evidence_links`** | Heuristic groupings; scores and **reasons** on links |
| **`incidents`** / **`incident_evidence`** | Promoted, reviewed incident bundles |

**Typical workflow:** `fetch` → `extract` (optional) → `candidates generate` → `candidates approve` → `incidents promote` → `report`.

**Tests (dev):** `pip install -e ".[dev]"` then `pytest`.

---

## License

This project is licensed under the [MIT License](LICENSE).
