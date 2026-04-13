"""Extraction JSON normalization."""

from investigation_agent.processor.extractor import normalize_extraction_dict


def test_normalize_extraction_dict():
    raw = {
        "facility_name": "  X  ",
        "facility_type": "hospital",
        "location_text": "Gaza",
        "date_text": "",
        "casualties_text": None,
        "confidence": "0.5",
    }
    out = normalize_extraction_dict(raw)
    assert out["facility_name"] == "X"
    assert out["confidence"] == 0.5
    assert out["date_text"] == ""
