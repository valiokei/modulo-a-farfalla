"""Isolated inference entry point; also used for real-video acceptance runs."""
import argparse
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from .action_spotting import OpenSportsLibProvider


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--threshold", type=float, default=.01)
    args = parser.parse_args()
    os.environ.setdefault("OSL_PRETRAINED_WEIGHTS", "0")
    os.environ.setdefault("WANDB_MODE", "disabled")
    os.nice(10)
    args.output.mkdir(parents=True, exist_ok=True)
    def progress(percent, stage):
        temporary = args.output / "progress.tmp"
        temporary.write_text(json.dumps({"progress": percent, "stage": stage}))
        temporary.replace(args.output / "progress.json")
    started = time.monotonic()
    predictions = OpenSportsLibProvider(device=args.device, batch_size=args.batch_size, threshold=args.threshold).predict(args.video, args.output, progress)
    (args.output / "suggestions.json").write_text(json.dumps({"elapsed_seconds": time.monotonic()-started, "predictions": [asdict(p) for p in predictions]}, indent=2))
    progress(100, "Completed")


if __name__ == "__main__":
    main()
