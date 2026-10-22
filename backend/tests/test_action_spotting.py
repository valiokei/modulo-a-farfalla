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


def test_default_threads_leaves_two_logical_cpus_free(monkeypatch):
    from app import action_spotting
    monkeypatch.setattr(action_spotting.os, "sched_getaffinity", lambda pid: set(range(20)), raising=False)
    assert action_spotting.default_threads() == 18
    monkeypatch.setattr(action_spotting.os, "sched_getaffinity", lambda pid: {0, 1}, raising=False)
    assert action_spotting.default_threads() == 1


def test_inference_windows_are_reported_as_progress():
    import types
    from app.action_spotting import _report_windows
    class tqdm:  # the slice of the tqdm API the OpenSportsLib loop relies on
        def __init__(self, iterable=None, **kwargs): self.iterable, self.total = iterable, len(iterable) if iterable is not None else None
        def __iter__(self): return iter(self.iterable)
    module = types.SimpleNamespace(tqdm=tqdm)
    seen = []
    _report_windows(module, lambda percent, stage: seen.append((percent, stage)))
    assert list(module.tqdm(range(4))) == [0, 1, 2, 3]
    assert [p for p, _ in seen] == [31, 52, 73, 95] and seen[-1][1] == "Action spotting 4/4"
    # Later bars (metric evaluation) are left untouched and do not report.
    assert module.tqdm is tqdm
