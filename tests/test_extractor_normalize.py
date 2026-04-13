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
