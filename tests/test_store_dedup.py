"""Evidence insertion deduplication."""

from investigation_agent.db.insert_types import InsertStatus
from investigation_agent.db.store import add_search_run, insert_evidence


def test_web_dedup_normalized_url(db_session):
    run = add_search_run(
        db_session,
        target_query="test",
        language="en",
        include_telegram=False,
        include_web=True,
        max_web_results=5,
    )
    db_session.commit()
    u = "https://example.com/article?utm_medium=email"
    r1, s1 = insert_evidence(
        db_session,
        search_run_id=run.id,
        target_query="test",
        source_type="web",
        source_url=u,
        raw_text="hello world " * 10,
        fetch_status="ok",
    )
    assert s1 == InsertStatus.INSERTED
    r2, s2 = insert_evidence(
        db_session,
        search_run_id=run.id,
        target_query="test",
        source_type="web",
        source_url="https://example.com/article?utm_campaign=y",
        raw_text="different body " * 10,
        fetch_status="ok",
    )
    assert s2 == InsertStatus.DUPLICATE_URL
    assert r2 is None


def test_telegram_dedup_message_id(db_session):
    run = add_search_run(
        db_session,
        target_query="t",
        language="en",
        include_telegram=True,
        include_web=False,
        max_web_results=0,
    )
    db_session.commit()
    a, s1 = insert_evidence(
        db_session,
        search_run_id=run.id,
        target_query="t",
        source_type="telegram",
        source_url="https://t.me/c/123/456",
        raw_text="x",
        channel_username="chan",
        message_id=99,
        fetch_status="ok",
    )
    b, s2 = insert_evidence(
        db_session,
        search_run_id=run.id,
        target_query="t",
        source_type="telegram",
        source_url="https://t.me/c/123/456",
        raw_text="x",
        channel_username="chan",
        message_id=99,
        fetch_status="ok",
    )
    assert s1 == InsertStatus.INSERTED
    assert s2 == InsertStatus.DUPLICATE_TELEGRAM
    assert b is None
