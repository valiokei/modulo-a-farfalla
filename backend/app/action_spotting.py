"""Official model adapters. Predictions remain unconfirmed, with unknown identities."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from bisect import bisect_left, insort
import json
import math

MODEL_ID = "OpenSportsLab/OSL-loc-snbas-2025-e2e"
MODEL_REVISION = "54e24a663a5a0ed057ef12cf16d9460d270ddc6e"
ACTIONS = ["PASS", "DRIVE", "HEADER", "HIGH PASS", "OUT", "CROSS", "THROW IN", "SHOT", "BALL PLAYER BLOCK", "PLAYER SUCCESSFUL TACKLE", "FREE KICK", "GOAL"]
CATEGORIES = dict(zip(ACTIONS, ["Pass", "Carry", "Header", "High Pass", "Ball Out", "Cross", "Throw-in", "Shot", "Block", "Tackle", "Free Kick", "Goal"]))


@dataclass(frozen=True)
class ActionPrediction:
    action: str
    timestamp: float
    confidence: float
    model: str
    model_version: str
    source: str = "NEURAL_MODEL"


class ActionSpottingProvider(ABC):
    @abstractmethod
    def predict(self, video: Path, work_dir: Path, progress) -> list[ActionPrediction]: ...


def parse_predictions(payload: dict, revision: str, threshold: float = .5) -> list[ActionPrediction]:
    if not isinstance(payload.get("data"), list):
        raise ValueError("OpenSportsLib returned an invalid prediction payload")
    predictions = []
    for sample in payload["data"]:
        for event in sample.get("events", []):
            action = event["label"]
            timestamp = float(event["position_ms"]) / 1000
            confidence = float(event["confidence"])
            if action not in ACTIONS or not math.isfinite(timestamp) or timestamp < 0:
                raise ValueError("Invalid action or timestamp in model output")
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("Invalid model confidence")
            if confidence >= threshold:
                predictions.append(ActionPrediction(action, timestamp, confidence, MODEL_ID, revision))
    # Official infer() returns high-recall frame candidates. Suppress only nearby
    # candidates of the same class, retaining their actual model probabilities.
    retained = []
    times_by_action = {action: [] for action in ACTIONS}
    for prediction in sorted(predictions, key=lambda p: p.confidence, reverse=True):
        times = times_by_action[prediction.action]
        index = bisect_left(times, prediction.timestamp)
        neighbours = times[max(0,index-1):index+1]
        if not any(abs(t-prediction.timestamp) <= 1 for t in neighbours):
            retained.append(prediction)
            insort(times, prediction.timestamp)
    return sorted(retained, key=lambda p: p.timestamp)


class OpenSportsLibProvider(ActionSpottingProvider):
    def __init__(self, device="auto", batch_size=1, threads=2, threshold=.5):
        self.device = device
        self.batch_size = max(1, min(16, batch_size))
        self.threads = max(1, min(4, threads))
        self.threshold = threshold

    def predict(self, video: Path, work_dir: Path, progress) -> list[ActionPrediction]:
        import torch
        from huggingface_hub import snapshot_download
        from omegaconf import OmegaConf
        from opensportslib.apis import LocalizationModel
        from opensportslib.core.utils.config import load_config_omega, namespace_to_omegaconf

        torch.set_num_threads(self.threads)
        device = "cuda" if torch.cuda.is_available() and self.device != "cpu" else "cpu"
        if self.device == "cuda" and device != "cuda":
            raise RuntimeError("CUDA requested but unavailable. AMD VA-API accelerates video encoding, not CUDA inference.")
        work_dir.mkdir(parents=True, exist_ok=True)
        progress(5, "Loading action model")
        snapshot = Path(snapshot_download(MODEL_ID, revision=MODEL_REVISION, allow_patterns=["config.yaml", "model.pt"]))
        revision = snapshot.name
        cfg = namespace_to_omegaconf(load_config_omega(str(snapshot / "config.yaml")))
        manifest = work_dir / "input.json"
        manifest.write_text(json.dumps({"version": "2.0", "task": "action_spotting", "labels": {"action": {"type": "single_label", "labels": ACTIONS}}, "data": [{"id": video.stem, "inputs": [{"type": "video", "path": str(video.resolve()), "fps": 25}], "metadata": {"annotation_status": "unlabeled"}, "events": []}]}))
        # Keep the official checkpoint architecture and preprocessing. Only runtime paths/resources change.
        dali = False
        if device == "cuda" and not torch.version.hip:
            try:
                import nvidia.dali  # noqa: F401
                dali = True
            except ImportError:
                pass
        overrides = {"SYSTEM.device": device, "SYSTEM.gpu.count": 1 if device == "cuda" else 0, "SYSTEM.paths.save_dir": str(work_dir / "runtime"), "TRAIN.execution.multi_gpu": False, "DATA.common.runtime.loader_backend": "dali" if dali else "opencv", "DATA.common.splits.test.type": "VideoGameWithDaliVideo" if dali else "VideoGameWithOpencvVideo", "DATA.common.splits.test.annotation_path": str(manifest), "DATA.common.splits.test.source_path": str(video.parent.resolve()), "DATA.common.splits.test.dataloader.batch_size": self.batch_size, "DATA.common.splits.test.dataloader.num_workers": 0, "DATA.common.splits.test.dataloader.pin_memory": device == "cuda"}
        for key, value in overrides.items():
            OmegaConf.update(cfg, key, value, force_add=True)
        config_path = work_dir / "config.yaml"
        OmegaConf.save(cfg, config_path)
        model = LocalizationModel(config=str(config_path), weights=str(snapshot / "model.pt"))
        model.config.SYSTEM.paths.work_dir = str(work_dir)
        progress(10, "Action spotting")
        while True:
            try:
                predictions = model.infer(test_set=str(manifest), use_wandb=False)
                break
            except torch.cuda.OutOfMemoryError:
                if self.batch_size == 1:
                    raise RuntimeError("Insufficient GPU memory even at batch size 1")
                self.batch_size = max(1, self.batch_size // 2)
                model.config.DATA.common.splits.test.dataloader.batch_size = self.batch_size
                torch.cuda.empty_cache()
        (work_dir / "predictions.json").write_text(json.dumps(predictions))
        (work_dir / "provenance.json").write_text(json.dumps({"model": MODEL_ID, "revision": revision, "device": device, "decoder": "dali" if dali else "opencv", "batch_size": self.batch_size}))
        progress(95, "Finalizing suggestions")
        return parse_predictions(predictions, revision, self.threshold)
