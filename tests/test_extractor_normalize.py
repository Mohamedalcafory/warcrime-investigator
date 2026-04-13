"""Extraction JSON normalization."""

from investigation_agent.processor.extractor import normalize_extraction_dict


def test_normalize_extraction_dict():
    raw = {
        "facility_name": "  X  ",
        "facility_type": "hospital",
        "location_text": "Gaza",
        "date_text": "",
        "attack_occurred": True,
        "attack_type": "shelling",
        "attack_date_text": "2024-01",
        "damage_text": "roof hit",
        "casualties_text": None,
        "perpetrator_claim_text": "",
        "confidence": "0.5",
    }
    out = normalize_extraction_dict(raw)
    assert out["facility_name"] == "X"
    assert out["confidence"] == 0.5
    assert out["date_text"] == ""
    assert out["attack_occurred"] is True
    assert out["attack_type"] == "shelling"
    assert out["attack_date_text"] == "2024-01"
    assert out["facility_attack_relation"] == "unclear"
    assert out["facility_target_object"] == "unknown"


def test_attack_date_falls_back_to_date_text():
    out = normalize_extraction_dict(
        {
            "facility_type": "hospital",
            "date_text": "March 2024",
            "attack_occurred": False,
            "attack_type": "unknown",
            "confidence": 0.3,
        }
    )
    assert out["attack_date_text"] == "March 2024"


def test_normalize_extraction_dict_relation_fields():
    out = normalize_extraction_dict(
        {
            "facility_type": "hospital",
            "facility_attack_relation": "direct_hit",
            "facility_target_object": "main_building",
            "facility_attack_relation_confidence": 0.9,
            "attack_occurred": True,
            "attack_type": "airstrike",
            "confidence": 0.8,
        }
    )
    assert out["facility_attack_relation"] == "direct_hit"
    assert out["facility_target_object"] == "main_building"
    assert out["facility_attack_relation_confidence"] == 0.9


def test_normalize_extraction_dict_invalid_relation_defaults():
    out = normalize_extraction_dict(
        {
            "facility_type": "hospital",
            "facility_attack_relation": "not_a_real_label",
            "facility_target_object": "nope",
            "attack_occurred": False,
            "attack_type": "unknown",
            "confidence": 0.1,
        }
    )
    assert out["facility_attack_relation"] == "unclear"
    assert out["facility_target_object"] == "unknown"
