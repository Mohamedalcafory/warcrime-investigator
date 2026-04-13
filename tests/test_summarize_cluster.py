"""summarize command cluster-id path."""

from unittest.mock import patch

import pytest
import typer

from investigation_agent.db.insert_types import InsertStatus
from investigation_agent.db.schema import CandidateCluster, CandidateEvidenceLink
from investigation_agent.db.store import add_search_run, insert_evidence


@patch("investigation_agent.cli.chat_completion", return_value="Summary [evidence:1]")
def test_summarize_by_cluster_id_uses_linked_evidence(mock_chat, db_session):
    from investigation_agent.cli import cmd_summarize

    run = add_search_run(
        db_session,
        target_query="hospital",
        language="en",
        include_telegram=False,
        include_web=True,
        max_web_results=5,
    )
    db_session.commit()

    r1, s1 = insert_evidence(
        db_session,
        search_run_id=run.id,
        target_query="hospital",
        source_type="web",
        source_url="https://ex.com/a",
        raw_text="first article " * 50,
        fetch_status="ok",
    )
    r2, s2 = insert_evidence(
        db_session,
        search_run_id=run.id,
        target_query="hospital",
        source_type="web",
        source_url="https://ex.com/b",
        raw_text="second article " * 50,
        fetch_status="ok",
    )
    assert s1 == InsertStatus.INSERTED and s2 == InsertStatus.INSERTED
    assert r1 is not None and r2 is not None

    cluster = CandidateCluster(status="pending")
    db_session.add(cluster)
    db_session.flush()
    db_session.add(CandidateEvidenceLink(cluster_id=cluster.id, evidence_id=r1.id, reasons_json="[]", confidence=0.8))
    db_session.add(CandidateEvidenceLink(cluster_id=cluster.id, evidence_id=r2.id, reasons_json="[]", confidence=0.8))
    db_session.commit()

    def _fake_get_session_factory():
        def _session_factory():
            return db_session

        return _session_factory

    with patch("investigation_agent.cli.get_session_factory", _fake_get_session_factory):
        cmd_summarize(
            target=None,
            ids=None,
            cluster_id=cluster.id,
            limit=8,
            approved_only=False,
        )

    mock_chat.assert_called_once()
    prompt = mock_chat.call_args.args[0][1]["content"]
    assert f"evidence_id={r1.id}" in prompt
    assert f"evidence_id={r2.id}" in prompt


def test_summarize_rejects_multiple_selectors():
    from investigation_agent.cli import cmd_summarize

    with pytest.raises(typer.Exit) as ex:
        cmd_summarize(
            target="hospital",
            ids="1:2",
            cluster_id=None,
            limit=8,
            approved_only=False,
        )
    assert ex.value.exit_code == 1
