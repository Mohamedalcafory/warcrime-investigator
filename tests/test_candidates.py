"""Candidate cluster generation."""

import json

from investigation_agent.db.insert_types import InsertStatus
from investigation_agent.db.store import add_search_run, insert_evidence
from investigation_agent.processor.review_queue import generate_candidate_clusters


def test_generate_cluster_same_target(db_session):
    run = add_search_run(
        db_session,
        target_query="hospital",
        language="en",
        include_telegram=False,
        include_web=True,
        max_web_results=5,
    )
    db_session.commit()
    for i in range(2):
        url = f"https://news.example.com/a{i}"
        insert_evidence(
            db_session,
            search_run_id=run.id,
            target_query="hospital",
            source_type="web",
            source_url=url,
            raw_text=("attack on hospital " * 20) + f" unique{i}",
            fetch_status="ok",
        )
        db_session.commit()

    n = generate_candidate_clusters(db_session, evidence_limit=10, min_score=0.25, max_pairs=500)
    db_session.commit()
    assert n >= 1


def test_pair_reasons_json(db_session):
    run = add_search_run(
        db_session,
        target_query="same",
        language="en",
        include_telegram=False,
        include_web=True,
        max_web_results=5,
    )
    db_session.commit()
    r1, _ = insert_evidence(
        db_session,
        search_run_id=run.id,
        target_query="same",
        source_type="web",
        source_url="https://x.com/1",
        raw_text="body one " * 100,
        classification_json=json.dumps({"facility_type": "hospital", "location": "Gaza"}),
        fetch_status="ok",
    )
    r2, _ = insert_evidence(
        db_session,
        search_run_id=run.id,
        target_query="same",
        source_type="web",
        source_url="https://y.com/2",
        raw_text="body two " * 100,
        classification_json=json.dumps({"facility_type": "hospital", "location": "Gaza"}),
        fetch_status="ok",
    )
    db_session.commit()
    assert r1 and r2
    n = generate_candidate_clusters(db_session, evidence_limit=10, min_score=0.4, max_pairs=500)
    db_session.commit()
    assert n >= 1
