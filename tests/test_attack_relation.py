"""Facility vs attack relation heuristics (ingest filter + infer)."""

from pathlib import Path

import pytest

from investigation_agent.processor.attack_filter import (
    INGEST_KEEP_RELATIONS,
    infer_facility_attack_relation,
    passes_attack_on_civil_facility_filter,
)


def test_infer_direct_hit_en():
    assert (
        infer_facility_attack_relation(
            target_query="",
            body="Witnesses said the hospital was shelled and the emergency ward was damaged.",
        )
        == "direct_hit"
    )


def test_infer_inside_compound():
    r = infer_facility_attack_relation(
        target_query="field hospital",
        body="Mortar fire landed in the hospital courtyard; staff took cover inside the compound.",
    )
    assert r == "inside_compound"


def test_infer_nearby():
    r = infer_facility_attack_relation(
        target_query="Al Shifa",
        body="An explosion near the hospital shook windows; several wounded were brought in.",
    )
    assert r == "adjacent_or_nearby"


def test_infer_associated_ambulance():
    r = infer_facility_attack_relation(
        target_query="Gaza hospital",
        body="An ambulance marked with the hospital logo was hit by shrapnel on the road.",
    )
    assert r == "associated_asset_hit"


def test_infer_associated_arabic_ambulance():
    r = infer_facility_attack_relation(
        target_query="مستشفى",
        body="قُصفت سيارة إسعاف أثناء نقل الجرحى من المستشفى.",
    )
    assert r == "associated_asset_hit"


BODY_DIRECTOR = (
    "The hospital director said airstrikes elsewhere in the city had killed dozens overnight."
)


def test_infer_context_only_director():
    r = infer_facility_attack_relation(target_query="Rafah hospital", body=BODY_DIRECTOR)
    assert r == "facility_used_as_context_only"
    assert not passes_attack_on_civil_facility_filter(target_query="Rafah hospital", body=BODY_DIRECTOR)


def test_infer_context_only_arabic_spokesperson():
    r = infer_facility_attack_relation(
        target_query="مستشفى الشفاء",
        body="المتحدث باسم وزارة الصحة قال إن القصف على المناطق السكنية أسفر عن قتلى.",
    )
    assert r == "facility_used_as_context_only"


def test_no_attack_on_facility():
    r = infer_facility_attack_relation(
        target_query="clinic",
        body="The clinic expanded pediatric services and added two new specialists.",
    )
    assert r == "no_attack_on_facility"


def test_ingest_keep_relations_cover_expected():
    assert "direct_hit" in INGEST_KEEP_RELATIONS
    assert "facility_used_as_context_only" not in INGEST_KEEP_RELATIONS
    assert "unclear" not in INGEST_KEEP_RELATIONS


_FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("relation_direct_hit_en.txt", "direct_hit"),
        ("relation_inside_compound_en.txt", "inside_compound"),
        ("relation_nearby_en.txt", "adjacent_or_nearby"),
        ("relation_associated_ambulance_en.txt", "associated_asset_hit"),
        ("relation_context_only_en.txt", "facility_used_as_context_only"),
    ],
)
def test_relation_fixtures_golden(filename: str, expected: str) -> None:
    body = (_FIXTURES / filename).read_text(encoding="utf-8")
    assert infer_facility_attack_relation(target_query="Gaza hospital blast", body=body) == expected
