import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipper.media import MediaError, map_scene_subtitles, render_subtitle_segments, transcribe_gemini, transcribe_openai_current
from clipper import db
from clipper.subtitles import (
    PRESETS,
    composition_fingerprint,
    composition_signature,
    export_subtitle_file,
    gemini_word_annotations,
    group_word_segments,
    parse_subtitle_file,
    subtitle_content_fingerprint,
    valid_word_alignment,
    validate_translation,
)


def run():
    srt = """1
00:00:00,500 --> 00:00:01,750
Hello, world!

2
00:00:02,000 --> 00:00:03,000
Second cue
"""
    cues, warnings = parse_subtitle_file(srt, "srt", 5)
    assert len(cues) == 2 and not warnings
    assert cues[0]["start"] == 0.5 and cues[0]["end"] == 1.75
    round_trip, _ = parse_subtitle_file(export_subtitle_file(cues, "srt"), "srt", 5)
    assert [(item["start"], item["end"], item["text"]) for item in round_trip] == [
        (item["start"], item["end"], item["text"]) for item in cues
    ]

    vtt = "WEBVTT\n\n00:01.250 --> 00:02.500\nVTT cue\n"
    vtt_cues, _ = parse_subtitle_file(vtt, "vtt", 5)
    assert vtt_cues[0]["start"] == 1.25 and vtt_cues[0]["end"] == 2.5
    assert export_subtitle_file(vtt_cues, "vtt").startswith("WEBVTT\n")

    out_of_range, warnings = parse_subtitle_file(
        "1\n00:00:06,000 --> 00:00:07,000\nOutside\n", "srt", 5,
    )
    assert out_of_range == [] and warnings
    clamped, warnings = parse_subtitle_file(
        "1\n00:00:04,000 --> 00:00:06,000\nClamp me\n", "srt", 5, clamp=True,
    )
    assert clamped[0]["end"] == 5 and warnings
    overlapping, warnings = parse_subtitle_file(
        "1\n00:00:00,000 --> 00:00:02,000\nOne\n\n2\n00:00:01,000 --> 00:00:03,000\nTwo\n", "srt", 5,
    )
    assert len(overlapping) == 2 and any("overlap" in item for item in warnings)

    words = [
        {"id": "w1", "text": "Hello", "start": 0, "end": 0.3},
        {"id": "w2", "text": "world!", "start": 0.31, "end": 0.8},
    ]
    grouped = group_word_segments(words)
    assert grouped[0]["text"] == "Hello world!" and grouped[0]["words"] == words
    assert grouped[0]["word_alignment_reviewed"] is True and valid_word_alignment(grouped[0])
    assert "subtitle_caption_mode" not in PRESETS["Word Pop"]
    assert PRESETS["Word Pop"]["subtitle_color"] == "#FFDF36"
    word_pop_segment = {
        "id": "manual-words", "start": 0, "end": 2, "text": "I'm gonna build rumah!",
        "word_alignment_reviewed": True,
        "words": [
            {"id": "w1", "text": "I'm", "start": 0.05, "end": 0.2},
            {"id": "w2", "text": "gonna", "start": 0.22, "end": 0.4},
            {"id": "w3", "text": "build", "start": 0.45, "end": 0.8},
            {"id": "w4", "text": "rumah!", "start": 0.9, "end": 1.3},
        ],
    }
    assert valid_word_alignment(word_pop_segment)
    assert not valid_word_alignment({key: value for key, value in word_pop_segment.items() if key != "word_alignment_reviewed"})
    assert not valid_word_alignment({**word_pop_segment, "words": [{**word_pop_segment["words"][0], "end": None}]})
    assert not valid_word_alignment({**word_pop_segment, "words": [{**word_pop_segment["words"][0], "start": "0.05"}, *word_pop_segment["words"][1:]]})
    assert not valid_word_alignment({**word_pop_segment, "words": [{**word_pop_segment["words"][0], "start": True}, *word_pop_segment["words"][1:]]})
    split_scenes = [
        {"id": "first", "source_start": 0, "source_end": 0.5, "order": 0},
        {"id": "second", "source_start": 0.5, "source_end": 2, "order": 1},
    ]
    split_mapped = map_scene_subtitles(
        {"id": "word-pop", "start": 0, "end": 2},
        {"scene_mode": "multi", "scenes": split_scenes, "subtitle_timebase": "source", "subtitle_segments": [word_pop_segment]},
        [],
    )
    split_word_parts = [word for item in split_mapped for word in item["words"] if word["id"] == "w3"]
    assert len(split_word_parts) == 2 and split_word_parts[0]["source_end"] == split_word_parts[1]["source_start"]
    missing_timing_edit = {
        "scene_mode": "single", "scenes": [{"id": "scene", "source_start": 0, "source_end": 2, "order": 0}],
        "subtitle_enabled": True, "subtitle_caption_mode": "word_pop", "subtitle_display_mode": "original",
        "subtitle_timebase": "source", "subtitle_tracks": [], "subtitle_segments": [{"id": "manual", "start": 0, "end": 2, "text": "No word times."}],
    }
    try:
        render_subtitle_segments({"id": "word-pop", "start": 0, "end": 2}, missing_timing_edit, [], "a" * 64)
    except MediaError as exc:
        assert "word-level" in str(exc)
    else:
        raise AssertionError("Word Pop accepted cue-only timing")
    payload = {"steps": [{"content": [{"annotations": [
        {"type": "word_info", "text": "Hi", "start_offset": "0.1s", "end_offset": "0.4s", "speaker_id": "speaker-0"},
        {"type": "word_info", "text": "bad", "start_offset": "8s", "end_offset": "9s"},
    ]}]}]}
    annotated = gemini_word_annotations(payload, 2)
    assert len(annotated) == 1 and annotated[0]["speaker_id"] == "speaker-0"

    fingerprint = subtitle_content_fingerprint(cues)
    assert fingerprint == subtitle_content_fingerprint(list(reversed(cues)))
    expected = [{"id": "a", "start": 0, "end": 1, "text": "Hello"}]
    assert validate_translation({"segments": [{"id": "a", "text": "Halo"}]}, expected)[0]["text"] == "Halo"
    for response in (
        {"segments": [{"id": "wrong", "text": "Halo"}]},
        {"segments": [{"id": "a", "text": " "}]},
        {"segments": [{"id": "a", "text": "one"}, {"id": "extra", "text": "two"}]},
    ):
        try:
            validate_translation(response, expected)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid translation response accepted")

    clip = {"id": "clip", "start": 0, "end": 4}
    scenes = [{"id": "scene-a", "source_start": 0, "source_end": 2, "order": 0}]
    signature = composition_signature(scenes)
    fingerprint = composition_fingerprint("a" * 64, signature)
    edit = {
        "scene_mode": "multi", "scenes": scenes, "subtitle_enabled": True,
        "subtitle_active_track_id": "track-a", "subtitle_active_translation_id": None,
        "subtitle_tracks": [{
            "id": "track-a", "timebase": "output", "composition_signature": signature,
            "composition_fingerprint": fingerprint,
            "segments": [{"id": "cue-a", "start": 0.25, "end": 1.25, "text": "Timed"}],
        }],
    }
    assert render_subtitle_segments(clip, edit, [], "a" * 64)[0]["start"] == 0.25
    edit["subtitle_tracks"][0]["segments"][0]["text"] = "Edited"
    assert render_subtitle_segments(clip, edit, [], "a" * 64)[0]["text"] == "Edited"
    edit["subtitle_tracks"][0]["composition_signature"] = "stale"
    try:
        render_subtitle_segments(clip, edit, [], "a" * 64)
    except MediaError as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("stale output-time track rendered")

    class Response:
        def __init__(self, payload=b"", headers=None):
            self.payload, self.headers = payload, headers or {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return self.payload

    with tempfile.TemporaryDirectory() as temp:
        audio = Path(temp) / "composition.m4a"
        audio.write_bytes(b"synthetic audio bytes")
        requests = []

        def openai_reply(request, timeout=0):
            requests.append(request)
            return Response(b'{"text":"Synthetic transcript","language":"en"}')

        with patch.dict(os.environ, {"OPENAI_API_KEY": "stub"}), patch("clipper.media.urllib.request.urlopen", side_effect=openai_reply):
            result = transcribe_openai_current(audio, "english")
        assert result["text"] == "Synthetic transcript" and result["segments"] == []
        assert b"gpt-transcribe" in requests[0].data and b"name=\"language\"" in requests[0].data

        responses = [
            Response(headers={"X-Goog-Upload-URL": "https://upload.invalid/session"}),
            Response(b'{"file":{"name":"files/stub","uri":"https://files.invalid/stub"}}'),
            Response(json.dumps({"status": "completed", "steps": [{"content": [
                {"type": "text", "text": "Hi there"},
                {"type": "audio_transcription", "annotations": [
                    {"type": "word_info", "text": "Hi", "start_offset": "0s", "end_offset": "0.3s", "speaker_id": "speaker-0"},
                    {"type": "word_info", "text": "there.", "start_offset": "0.31s", "end_offset": "0.8s", "speaker_id": "speaker-0"},
                ]},
            ]}]}).encode()),
            Response(),
        ]
        gemini_requests = []

        def gemini_reply(request, timeout=0):
            gemini_requests.append(request)
            return responses.pop(0)

        with patch.dict(os.environ, {"GEMINI_API_KEY": "stub"}), patch("clipper.media.urllib.request.urlopen", side_effect=gemini_reply):
            result = transcribe_gemini(audio, "english", 1, threading.Event())
        interaction = json.loads(gemini_requests[2].data)
        assert interaction["model"] == "gemini-3.5-transcribe"
        assert interaction["generation_config"]["transcription_config"]["mode"]["timestamp_granularities"] == ["word"]
        assert len(result["words"]) == 2 and result["segments"][0]["text"] == "Hi there."
        assert gemini_requests[-1].get_method() == "DELETE"

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        paths = {
            "DATA_DIR": root / "data", "SOURCE_DIR": root / "sources", "ASSET_DIR": root / "assets",
            "WORK_DIR": root / "data" / "work", "CLIP_DIR": root / "clips", "MOOD_DIR": root / "mood",
            "DB_PATH": root / "data" / "clipper.sqlite3",
        }
        with patch.multiple(db, **paths):
            db.init_db()
            job_id = "interrupted-subtitle-job"
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,audio_codec,sha256,created_at) "
                    "VALUES('source-a','source.mp4','source.mp4',1,2,720,1280,'h264','aac',?,'now')", ("a" * 64,),
                )
                conn.execute(
                    "INSERT INTO jobs(id,source_id,kind,status,phase,options_json,created_at,updated_at) "
                    "VALUES(?, 'source-a','subtitle_transcribe','transcribing','transcribing','{}','now','now')", (job_id,),
                )
            (paths["WORK_DIR"] / f"{job_id}.m4a").write_bytes(b"temporary audio")
            db.init_db()
            assert not (paths["WORK_DIR"] / f"{job_id}.m4a").exists()
            with db.connect() as conn:
                status = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()["status"]
            assert status == "failed"

    print("subtitle parsing, fingerprint, word timing, translation, and stale-track checks passed")


if __name__ == "__main__":
    run()
