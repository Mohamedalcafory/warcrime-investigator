"""9-flag war-crimes classifier normalization."""

from investigation_agent.processor.classifier import WAR_CRIMES_BOOLEAN_KEYS, normalize_war_crimes_classifier


def test_normalize_war_crimes_classifier_defaults():
    out = normalize_war_crimes_classifier({})
    for k in WAR_CRIMES_BOOLEAN_KEYS:
        assert k in out
        assert isinstance(out[k], bool)
        assert f"{k}_confidence" in out
    assert "explanation" in out
    assert "overall_confidence" in out
    assert out.get("facility_attack_relation") == "unclear"
    assert out.get("facility_attack_relation_confidence") == 0.0


def test_normalize_war_crimes_classifier_parses_strings():
    out = normalize_war_crimes_classifier(
        {
            "civilian_deaths": "true",
            "is_genocidal": False,
            "explanation": "test",
            "overall_confidence": 0.7,
        }
    )
    assert out["civilian_deaths"] is True
    assert out["is_genocidal"] is False
    assert out["overall_confidence"] == 0.7


def test_normalize_war_crimes_classifier_optional_civil_keys():
    out = normalize_war_crimes_classifier(
        {
            "targeting_facilities": True,
            "civil_facility_attack_relevance": 0.8,
            "civil_facility_attack_rationale": "قصف المستشفى",
            "explanation": "x",
            "overall_confidence": 0.6,
        }
    )
    assert out["civil_facility_attack_relevance"] == 0.8
    assert "مستشفى" in out["civil_facility_attack_rationale"]
