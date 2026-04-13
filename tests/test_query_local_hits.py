"""query command local-hit path (mocked Chroma + no fetch)."""

from unittest.mock import patch

from investigation_agent.db.insert_types import InsertStatus
from investigation_agent.db.store import add_search_run, insert_evidence
from investigation_agent.retrieval.chroma_store import SemanticHit


@patch("investigation_agent.cli.chat_completion", return_value="Summary [evidence:1]")
@patch("investigation_agent.cli.chroma_semantic_search")
def test_query_uses_local_hits_without_fetch(mock_chroma, mock_chat, db_session):
    from investigation_agent.cli import cmd_query

    run = add_search_run(
        db_session,
        target_query="hospital",
        language="en",
        include_telegram=False,
        include_web=True,
        max_web_results=5,
    )
    db_session.commit()
    r, st = insert_evidence(
        db_session,
        search_run_id=run.id,
        target_query="hospital",
        source_type="web",
        source_url="https://ex.com/a",
        raw_text="attack on hospital " * 30,
        fetch_status="ok",
    )
    assert st == InsertStatus.INSERTED
    db_session.commit()

    mock_chroma.return_value = [
        SemanticHit(evidence_id=r.id, distance=0.1, source_url=r.source_url, preview="x"),
    ]

    def _fake_get_session_factory() -> object:
        def _session_factory() -> object:
            return db_session

        return _session_factory

    with patch("investigation_agent.cli.get_session_factory", _fake_get_session_factory):
        cmd_query(
            query_text="hospital attack",
            target=None,
            fetch_threshold=1,
            local_only=True,
            auto_fetch=True,
            lang="en",
            max_web=5,
            web_date_filter="none",
            web=True,
            telegram=False,
        )

    mock_chat.assert_called_once()
