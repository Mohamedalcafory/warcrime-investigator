"""Incidents and promotion from candidate clusters."""

from __future__ import annotations

import json

from investigation_agent.db.insert_types import InsertStatus
from investigation_agent.db.schema import CandidateCluster, CandidateEvidenceLink
from investigation_agent.db.store import (
    add_search_run,
    insert_evidence,
    promote_candidate_cluster_to_incident,
)


def test_promote_cluster_idempotent(db_session):
    run = add_search_run(
        db_session,
        target_query="hospital",
        language="en",
        include_telegram=False,
        include_web=True,
        max_web_results=5,
    )
    db_session.commit()
    r1, st1 = insert_evidence(
        db_session,
        search_run_id=run.id,
        target_query="hospital",
        source_type="web",
        source_url="https://a.example.com/1",
        raw_text="text one " * 50,
        fetch_status="ok",
    )
    r2, st2 = insert_evidence(
        db_session,
        search_run_id=run.id,
        target_query="hospital",
        source_type="web",
        source_url="https://b.example.com/2",
        raw_text="text two " * 50,
        fetch_status="ok",
    )
    assert st1 == InsertStatus.INSERTED and st2 == InsertStatus.INSERTED
    assert r1 and r2
    c = CandidateCluster(status="approved", title="Test cluster")
    db_session.add(c)
    db_session.flush()
    for eid in (r1.id, r2.id):
        db_session.add(
            CandidateEvidenceLink(
                cluster_id=c.id,
                evidence_id=eid,
                reasons_json=json.dumps(["same_target_query"], ensure_ascii=False),
                confidence=0.8,
            )
        )
    db_session.commit()

    inc = promote_candidate_cluster_to_incident(db_session, c.id)
    assert inc is not None
    assert inc.source_cluster_id == c.id
    db_session.commit()

    again = promote_candidate_cluster_to_incident(db_session, c.id)
    assert again is not None
    assert again.id == inc.id


def test_promote_requires_approved(db_session):
    c = CandidateCluster(status="pending", title="x")
    db_session.add(c)
    db_session.commit()
    try:
        promote_candidate_cluster_to_incident(db_session, c.id)
    except ValueError as e:
        assert "approved" in str(e).lower()
    else:
        raise AssertionError("expected ValueError")
