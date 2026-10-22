import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipper.analysis import parse_and_validate, transcript_chunks
from clipper.media import MediaError, _public_addresses, _write_ass
from clipper.providers import ProviderError, check_local


def run():
    chunks = transcript_chunks([
        {"start": 0, "end": 10, "text": "first"},
        {"start": 280, "end": 290, "text": "overlap"},
        {"start": 300, "end": 310, "text": "next"},
    ])
    assert len(chunks) == 2 and chunks[1][0]["start"] == 280

    candidates = parse_and_validate(
        {"clips": [
            {"start": 1, "end": 21, "title": "valid", "reason": "complete thought"},
            {"start": 2, "end": 20, "title": "duplicate", "reason": "same moment"},
            {"start": 89, "end": 120, "title": "outside", "reason": "bad duration"},
        ]},
        duration=100,
        minimum=15,
        maximum=30,
        limit=5,
    )
    assert len(candidates) == 1 and candidates[0]["title"] == "valid"

    padded = parse_and_validate(
        {"clips": [{"start": 12.2, "end": 18.8, "title": "hook", "reason": "strong opening"}]},
        duration=60,
        minimum=15,
        maximum=30,
        limit=3,
        segments=[
            {"start": 0, "end": 6, "text": "setup"},
            {"start": 6, "end": 12, "text": "hook"},
            {"start": 12, "end": 18, "text": "insight"},
            {"start": 18, "end": 24, "text": "context"},
            {"start": 24, "end": 30, "text": "ending"},
        ],
    )
    assert len(padded) == 1 and padded[0]["end"] - padded[0]["start"] == 18
    assert "expanded" in padded[0]["reason"]

    with tempfile.TemporaryDirectory() as temp:
        subtitle = Path(temp) / "highlight.ass"
        _write_ass(
            subtitle,
            [{"start": 1, "end": 4, "text": "phrase highlight"}],
            0,
            5,
            {"style": "Highlight", "subtitle_size": 48, "subtitle_position": 82,
             "subtitle_color": "#ffd700", "subtitle_overrides": {}},
            1280,
        )
        rendered_ass = subtitle.read_text(encoding="utf-8-sig")
        assert "&H0000D7FF" in rendered_ass and "Dialogue: 0,0:00:01.00,0:00:04.00" in rendered_ass

    for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"):
        try:
            _public_addresses(address)
        except MediaError:
            pass
        else:
            raise AssertionError(f"private address accepted: {address}")

    with patch.dict(os.environ, {"OLLAMA_URL": "http://127.0.0.1:11434", "OLLAMA_MODEL": "qwen2.5:1.5b"}):
        with patch("clipper.providers.urllib.request.urlopen", side_effect=URLError("offline")) as request, patch("clipper.providers.time.sleep"):
            try:
                check_local()
            except ProviderError as exc:
                assert "3 one-second checks" in str(exc)
            else:
                raise AssertionError("unavailable Ollama was accepted")
            assert request.call_count == 3
    print("core validation checks passed")


if __name__ == "__main__":
    run()
