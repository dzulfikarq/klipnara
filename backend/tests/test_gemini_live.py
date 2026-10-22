"""One opt-in Gemini Free Tier call using synthetic timestamped text only."""

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from clipper.analysis import parse_and_validate, prompt_for
from clipper.providers import analyze


def run():
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("Set GEMINI_API_KEY from a Free Tier project before running this live test.")
    segments = [
        {"start": 0, "end": 7, "text": "Pernahkah kamu mengira hemat energi hanya berarti mematikan lampu?"},
        {"start": 7, "end": 16, "text": "Padahal memilih peralatan efisien dan memakai cahaya alami dapat mengurangi listrik."},
        {"start": 16, "end": 25, "text": "Atur pendingin udara, matikan perangkat siaga, lalu gunakan lampu LED."},
        {"start": 25, "end": 34, "text": "Hemat energi bukan hidup dalam gelap, tetapi memakai tenaga saat dibutuhkan."},
    ]
    prompt = prompt_for(segments, 35, 15, 30, 3, "indonesia")
    started = time.perf_counter()
    raw, model, usage = analyze("gemini", prompt)  # Exactly one request; no retry/fallback.
    candidates = parse_and_validate(raw, duration=35, minimum=15, maximum=30, limit=3, segments=segments)
    if not candidates:
        raise SystemExit("Gemini returned no candidate with valid 15–30 second boundaries.")
    print(json.dumps({"model": model, "candidate_count": len(candidates), "candidates": candidates,
                      "usage": usage, "elapsed_seconds": round(time.perf_counter() - started, 2),
                      "input": "synthetic transcript/timestamps only; no media sent"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
