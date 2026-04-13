"""Deterministic attack-on-civil-facility ingest filter."""

from investigation_agent.processor.attack_filter import passes_attack_on_civil_facility_filter


def test_positive_hospital_attack_en():
    assert passes_attack_on_civil_facility_filter(
        target_query="Al Shifa Hospital",
        title="Airstrike hits hospital in Gaza",
        body="The hospital was damaged in an airstrike; several wounded.",
    )


def test_positive_arabic():
    assert passes_attack_on_civil_facility_filter(
        target_query="مستشفى",
        body="قصف جوي استهدف المستشفى وأسفر عن جرحى.",
    )


def test_negative_facility_only():
    assert not passes_attack_on_civil_facility_filter(
        target_query="hospital supplies",
        body="The hospital received new MRI machines and expanded the pediatric ward.",
    )


def test_negative_no_facility_context():
    assert not passes_attack_on_civil_facility_filter(
        target_query="news",
        body="The military announced exercises in the training area.",
    )


def test_target_query_brings_facility_type():
    """When body omits 'hospital' but target names it."""
    assert passes_attack_on_civil_facility_filter(
        target_query="Khan Younis hospital attack",
        body="Several killed and wounded in the strike overnight.",
    )
