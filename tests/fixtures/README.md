# Evaluation fixtures (Phase 7)

Small text samples for manual or scripted checks:

- `sample_evidence_en.txt` — English news-style snippet (generic).
- `sample_evidence_ar.txt` — Arabic snippet (generic).

Tests use an in-memory DB with synthetic rows; these files are for human review and future golden-file expansion.

For **attack-on-civil-facility** scenarios, prefer snippets that combine facility references with attack/violence language (ingest filter + LLM prompts assume that focus).
