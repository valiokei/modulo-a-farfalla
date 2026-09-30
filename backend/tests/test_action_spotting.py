import pytest
from app.action_spotting import parse_predictions, MODEL_ID


def test_neural_predictions_preserve_confidence_and_suppress_temporal_duplicates():
    events=[{"label":"PASS","position_ms":1000,"confidence":.02},{"label":"PASS","position_ms":1200,"confidence":.04},{"label":"SHOT","position_ms":1200,"confidence":.03}]
    predictions=parse_predictions({"data":[{"events":events}]},"revision-test",.01)
    assert [(p.action,p.confidence) for p in predictions]==[("PASS",.04),("SHOT",.03)]
    assert all(p.model==MODEL_ID and p.source=="NEURAL_MODEL" for p in predictions)
    assert parse_predictions({"data":[]},"revision-test")==[]


def test_invalid_predictions_are_not_saved_as_events():
    with pytest.raises(ValueError):
        parse_predictions({"data":[{"events":[{"label":"PASS","position_ms":1000,"confidence":float('nan')}]}]},"revision-test")
