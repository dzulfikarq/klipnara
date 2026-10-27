import json
import os
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipper.analysis import RANK_SCHEMA, candidate_schema, parse_and_validate, parse_ranking, ranking_schema, token_bounded_chunks, transcript_chunks
from clipper.media import MediaError, _audio_filters, _public_addresses, _write_ass, map_scene_subtitles, output_scenes, probe, transcript_cache_matches, transcription_config_key, transcription_model_id, transcribe
from clipper.providers import ProviderError, _post, _timeout_seconds, analyze, check_local, count_prompt_tokens, local_limits


def run():
    clip = {"id": "multi", "start": 60, "end": 90}
    multi_edit = {
        "scene_mode": "multi",
        "scenes": [
            {"id": "later", "source_start": 70, "source_end": 75, "order": 1},
            {"id": "first", "source_start": 10, "source_end": 13, "order": 0},
            {"id": "repeat", "source_start": 70, "source_end": 74, "order": 2},
        ],
        "subtitle_timebase": "source",
        "subtitle_segments": [
            {"id": "cross", "start": 72, "end": 77, "text": "Across cut"},
            {"id": "first-caption", "start": 11.5, "end": 13.5, "text": "First"},
        ],
    }
    timeline = output_scenes(clip, multi_edit)
    assert [(scene["timeline_start"], scene["timeline_end"]) for scene in timeline] == [(0, 3), (3, 8), (8, 12)]
    mapped = map_scene_subtitles(clip, multi_edit, [])
    assert [(item["id"], item["start"], item["end"]) for item in mapped] == [
        ("first-first-caption", 1.5, 3), ("later-cross", 5, 8), ("repeat-cross", 10, 12),
    ]
    legacy_timeline = output_scenes(clip, {"trim_start": 2, "trim_end": 5, "scenes": multi_edit["scenes"]})
    assert (legacy_timeline[0]["source_start"], legacy_timeline[0]["source_end"], legacy_timeline[0]["duration"]) == (62, 65, 3)
    filters = _audio_filters({"audio": {"volume": 0.8, "normalize": True, "limiter": True, "fade_in": 1, "fade_out": 2}}, 10)
    assert filters == ["volume=0.800", "loudnorm=I=-18.0:TP=-1.5:LRA=11", "alimiter=limit=0.95", "afade=t=in:st=0:d=1.000", "afade=t=out:st=8.000:d=2.000"]

    no_audio_probe = {"format": {"format_name": "mov,mp4,m4a", "duration": "60"}, "streams": [{
        "codec_type": "video", "codec_name": "h264", "width": 720, "height": 1280,
    }]}
    with patch("clipper.media.executable", return_value="ffprobe"), patch(
        "clipper.media.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(no_audio_probe)),
    ):
        probed = probe(Path("silent.mp4"))
    assert probed["audio_codec"] is None and probed["duration"] == 60

    assert candidate_schema(2)["properties"]["clips"]["maxItems"] == 2
    assert ranking_schema(3)["properties"]["ranking"]["maxItems"] == 3
    assert local_limits() == (4096, 1536, 2304)
    with patch.dict(os.environ, {"OLLAMA_TIMEOUT_SECONDS": "600"}):
        assert _timeout_seconds("OLLAMA_TIMEOUT_SECONDS", 1) == 600
    with patch.dict(os.environ, {"OLLAMA_TIMEOUT_SECONDS": "1801"}):
        try:
            _timeout_seconds("OLLAMA_TIMEOUT_SECONDS", 1)
        except ProviderError as exc:
            assert "between 1 and 1800" in str(exc)
        else:
            raise AssertionError("unbounded provider timeout was accepted")

    with tempfile.TemporaryDirectory() as temp:
        base_model, small_model = Path(temp) / "base.bin", Path(temp) / "small.bin"
        base_model.write_bytes(b"base-model")
        small_model.write_bytes(b"small-model")
        whisper = str(Path(sys.executable).resolve())
        with patch.dict(os.environ, {"WHISPER_CPP_PATH": whisper, "WHISPER_MODEL_PATH": str(base_model)}):
            base_id = transcription_model_id()
            cached = {"transcript_json": "[]", "transcript_config": transcription_config_key("auto"), "transcript_model": base_id}
            assert transcript_cache_matches(cached, "auto")
            assert not transcript_cache_matches(cached, "indonesia")
            with patch.dict(os.environ, {"WHISPER_MODEL_PATH": str(small_model)}):
                assert not transcript_cache_matches(cached, "auto")
            old_auto = {**cached, "transcript_config": "auto"}
            assert not transcript_cache_matches(old_auto, "auto")
        base_model.write_bytes(b"updated-base-model")
        with patch.dict(os.environ, {"WHISPER_CPP_PATH": whisper, "WHISPER_MODEL_PATH": str(base_model)}):
            assert not transcript_cache_matches(cached, "auto")

    assert transcription_config_key("indonesia") == "indonesia|loudnorm-i20-tp15-lra11-v1"
    assert transcription_config_key("auto") == "auto-detect-v1|loudnorm-i20-tp15-lra11-v1"
    with tempfile.TemporaryDirectory() as temp:
        commands = []

        def fake_whisper(command, cancel):
            commands.append(command)
            output = Path(command[command.index("-of") + 1] + ".json")
            output.write_text(json.dumps({
                "result": {"language": "id"},
                "transcription": [{"offsets": {"from": 0, "to": 1000}, "text": "uji"}],
            }), encoding="utf-8")

        with patch("clipper.media.WORK_DIR", Path(temp)), \
             patch("clipper.media.transcription_model_id", return_value="fixture"), \
             patch("clipper.media.executable", return_value="whisper-cli"), \
             patch("clipper.media._run", side_effect=fake_whisper), \
             patch("clipper.media.uuid.uuid4", side_effect=[SimpleNamespace(hex="auto"), SimpleNamespace(hex="id")]):
            transcribe(Path("fixture.wav"), "auto", None)
            transcribe(Path("fixture.wav"), "indonesia", None)
        assert commands[0][commands[0].index("-l") + 1] == "auto"
        assert commands[1][commands[1].index("-l") + 1] == "id"

    chunks = transcript_chunks([
        {"start": 0, "end": 10, "text": "first"},
        {"start": 280, "end": 290, "text": "overlap"},
        {"start": 300, "end": 310, "text": "next"},
    ])
    assert len(chunks) == 2 and chunks[1][0]["start"] == 280

    transcript = [
        {"start": index * 10, "end": index * 10 + 8, "text": f"segment {index}."}
        for index in range(8)
    ]
    bounded = token_bounded_chunks([transcript], lambda chunk: len(chunk), 4)
    assert all(len(chunk) <= 4 for chunk in bounded)
    assert {item["text"] for chunk in bounded for item in chunk} == {item["text"] for item in transcript}
    try:
        token_bounded_chunks([[transcript[0]]], lambda chunk: 5, 4)
    except ValueError as exc:
        assert "cannot be split safely" in str(exc)
    else:
        raise AssertionError("unsplittable oversized segment was accepted")

    ranked = parse_ranking(
        {"ranking": [{"id": 1, "reason": "best"}, {"id": True, "reason": "invalid"}, {"id": 1, "reason": "duplicate"}, {"id": 0, "reason": "next"}]},
        [{"title": "first"}, {"title": "second"}],
        2,
    )
    assert [item["title"] for item in ranked] == ["second", "first"]

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
        _write_ass(
            subtitle,
            [{"id": "stable-1", "start": 3, "end": 5, "text": "clip-relative"}],
            2,
            8,
            {"style": "Clean", "subtitle_size": 48, "subtitle_position": 82,
             "subtitle_color": "#ffffff", "subtitle_overrides": {}},
            1280,
            clip_relative=True,
        )
        assert "Dialogue: 0,0:00:01.00,0:00:03.00" in subtitle.read_text(encoding="utf-8-sig")
        word_pop = {
            "style": "Bold", "subtitle_size": 58, "subtitle_position": 70,
            "subtitle_color": "#FFDF36", "subtitle_outline_color": "#000000",
            "subtitle_outline": 4, "subtitle_shadow": 1, "subtitle_background": False,
            "subtitle_alignment": "center", "subtitle_caption_width": 85, "subtitle_safe_margin": 8,
            "subtitle_font": "Arial", "subtitle_overrides": {}, "subtitle_caption_mode": "word_pop",
            "subtitle_animation": "pop", "subtitle_animation_intensity": 0.12, "subtitle_animation_duration": 100,
        }
        pop_words = [{
            "start": 0.05, "end": 0.2, "text": "I'm", "id": "w1"},
            {"start": 0.22, "end": 0.32, "text": "gonna", "id": "w2"},
            {"start": 0.35, "end": 0.6, "text": "build", "id": "w3"},
            {"start": 0.7, "end": 1.2, "text": "pneumonoultramicroscopicsilicovolcanoconiosis", "id": "w4"},
        ]
        _write_ass(subtitle, [{"start": 0, "end": 1.5, "text": "Ignored sentence", "words": pop_words}], 0, 2, word_pop, 1280)
        word_pop_ass = subtitle.read_text(encoding="utf-8-sig")
        word_dialogues = [line for line in word_pop_ass.splitlines() if line.startswith("Dialogue:")]
        assert len(word_dialogues) == 4 and "Ignored sentence" not in word_pop_ass
        assert "#FFDF36" not in word_pop_ass and "\u0026H0036DFFF" in word_pop_ass
        assert "\\fscx88" in word_dialogues[2] and "\\fscx88" not in word_dialogues[0] and "\\fscx88" not in word_dialogues[1]
        assert "\\fscx104" in word_dialogues[2]
        assert "\\fs" in word_dialogues[3]
        word_pop["subtitle_animation"] = "scale"
        _write_ass(subtitle, [{"start": 0, "end": 1.5, "text": "Ignored sentence", "words": pop_words}], 0, 2, word_pop, 1280)
        scaled_dialogues = [line for line in subtitle.read_text(encoding="utf-8-sig").splitlines() if line.startswith("Dialogue:")]
        assert "\\fscx88" in scaled_dialogues[2] and "\\fscx104" not in scaled_dialogues[2]
        word_pop["subtitle_animation"] = "none"
        cut_words = [
            {"id": "cut-word", "text": "hello", "start": 0.4, "end": 0.5, "source_start": 1.0, "source_end": 1.1},
            {"id": "cut-word", "text": "hello", "start": 0.5, "end": 0.6, "source_start": 1.1, "source_end": 1.2},
        ]
        _write_ass(subtitle, [{"start": 0, "end": 1, "text": "hello", "words": cut_words}], 0, 1, word_pop, 1280)
        assert len([line for line in subtitle.read_text(encoding="utf-8-sig").splitlines() if line.startswith("Dialogue:")]) == 1
        cut_words[1]["source_start"] = 1.11
        _write_ass(subtitle, [{"start": 0, "end": 1, "text": "hello", "words": cut_words}], 0, 1, word_pop, 1280)
        assert len([line for line in subtitle.read_text(encoding="utf-8-sig").splitlines() if line.startswith("Dialogue:")]) == 2
        very_long = [{"id": "long", "text": "x" * 250, "start": 0.1, "end": 1.2}]
        _write_ass(subtitle, [{"start": 0, "end": 1.5, "text": "long", "words": very_long}], 0, 2, word_pop, 1280)
        long_dialogue = next(line for line in subtitle.read_text(encoding="utf-8-sig").splitlines() if line.startswith("Dialogue:"))
        assert "\\fs12" in long_dialogue and "\\fscx" in long_dialogue
        try:
            _write_ass(subtitle, [{"start": 0, "end": 0.1, "text": "Tiny", "words": [{"id": "tiny", "text": "Tiny", "start": 0.001, "end": 0.004}]}], 0, 2, word_pop, 1280)
        except MediaError as exc:
            assert "10 ms" in str(exc)
        else:
            raise AssertionError("ASS silently erased sub-centisecond word timing")
        _write_ass(subtitle, [{"start": 0, "end": 1.5, "text": "Ignored sentence", "words": pop_words}], 0, 2, word_pop, 1920)
        word_pop_1080 = subtitle.read_text(encoding="utf-8-sig")
        assert "PlayResY: 1920" in word_pop_1080 and "Style: Default,Arial,87," in word_pop_1080
        assert "&H00000000,&H80000000,-1,0,1,6,1.5,5," in word_pop_1080

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

    payloads = []

    def local_response(url, payload, headers=None, timeout=None):
        payloads.append(payload)
        return {"message": {"content": json.dumps({"ranking": []})}, "prompt_eval_count": 37, "eval_count": 1}

    with patch.dict(os.environ, {"OLLAMA_URL": "http://127.0.0.1:11434", "OLLAMA_MODEL": "qwen2.5:1.5b"}):
        with patch("clipper.providers.check_local"), patch("clipper.providers._post", side_effect=local_response):
            tokens, model, usage = count_prompt_tokens("synthetic transcript", RANK_SCHEMA)
            raw, _, _ = analyze("local", "synthetic transcript", RANK_SCHEMA, "clip_ranking")
    assert tokens == 37 and model == "qwen2.5:1.5b" and usage["completion_tokens"] == 1
    assert payloads[0]["options"]["num_ctx"] == 4096 and payloads[0]["options"]["num_predict"] == 1
    assert payloads[1]["options"]["num_ctx"] == 4096 and payloads[1]["options"]["num_predict"] == 1536
    assert payloads[0]["format"] == RANK_SCHEMA and payloads[1]["format"] == RANK_SCHEMA
    assert json.loads(raw) == {"ranking": []}

    model_response = {
        "candidates": [{"content": {"parts": [{"text": json.dumps({"clips": [{"start": 0, "end": 20, "title": "Hook", "reason": "Useful insight"}]})}]}}],
        "usageMetadata": {"promptTokenCount": 73, "candidatesTokenCount": 18},
    }
    with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-key", "GEMINI_MODEL": "gemini-3.5-flash-lite"}):
        with patch("clipper.providers._post", return_value=model_response) as send:
            raw, model, usage = analyze("gemini", "[0-20] Synthetic transcript for schema check")
        url, payload = send.call_args.args[:2]
        assert model == "gemini-3.5-flash-lite" and url.endswith("gemini-3.5-flash-lite:generateContent")
        assert send.call_args.kwargs["headers"] == {"x-goog-api-key": "test-only-key"}
        schema = payload["generationConfig"]["responseSchema"]
        assert schema["type"] == "OBJECT" and schema["properties"]["clips"]["type"] == "ARRAY"
        assert "additionalProperties" not in schema
        assert "video" not in payload and usage == {"promptTokenCount": 73, "candidatesTokenCount": 18}
        valid = parse_and_validate(raw, duration=30, minimum=15, maximum=30, limit=3)
        assert valid[0]["title"] == "Hook"

    with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-key", "GEMINI_MODEL": "gemini-3.6-flash"}):
        with patch("clipper.providers._post", return_value=model_response) as send:
            _, model, _ = analyze("gemini", "synthetic transcript")
        assert model == "gemini-3.6-flash" and "gemini-3.6-flash:generateContent" in send.call_args.args[0]

    gemini_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"
    with patch("clipper.providers.urllib.request.urlopen", side_effect=HTTPError(gemini_url, 429, "RESOURCE_EXHAUSTED", {}, BytesIO())):
        try:
            _post(gemini_url, {})
        except ProviderError as exc:
            assert "Free Tier quota" in str(exc) and "will not upgrade billing" in str(exc)
        else:
            raise AssertionError("Gemini HTTP 429 did not produce quota-specific error")
    print("core validation checks passed")


if __name__ == "__main__":
    run()
