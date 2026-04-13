"""classification_json merge behavior."""

import json

from investigation_agent.db.store import merge_classification_json
from investigation_agent.db.schema import Evidence
from investigation_agent.db.insert_types import InsertStatus
from investigation_agent.db.store import add_search_run, insert_evidence


def test_merge_preserves_war_crimes_classifier_nested(db_session):
    run = add_search_run(
        db_session,
        target_query="t",
        language="en",
        include_telegram=False,
        include_web=True,
        max_web_results=5,
    )
    db_session.commit()
    row, st = insert_evidence(
        db_session,
        search_run_id=run.id,
        target_query="t",
        source_type="web",
        source_url="https://example.com/x",
        raw_text="body " * 50,
        fetch_status="ok",
    )
    assert st == InsertStatus.INSERTED and row
    merge_classification_json(db_session, row.id, {"facility_type": "hospital"})
    db_session.commit()
    merge_classification_json(
        db_session,
        row.id,
        {"war_crimes_classifier": {"is_genocidal": True, "explanation": "a"}},
    )
    db_session.commit()
    merge_classification_json(
        db_session,
        row.id,
        {"war_crimes_classifier": {"civilian_deaths": False}},
    )
    db_session.commit()
    r2 = db_session.get(Evidence, row.id)
    data = json.loads(r2.classification_json or "{}")
    assert data.get("facility_type") == "hospital"
    wc = data.get("war_crimes_classifier") or {}
    assert wc.get("is_genocidal") is True
    assert wc.get("civilian_deaths") is False
    assert wc.get("explanation") == "a"
