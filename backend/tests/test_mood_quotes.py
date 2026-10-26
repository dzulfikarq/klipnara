import json
import os
import sys
import tempfile
import threading
import uuid
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ["CLIPPER_DATA_DIR"] = tempfile.mkdtemp(prefix="klipnara-mood-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from clipper.config import CLIP_DIR, SOURCE_DIR
from clipper.db import connect, init_db
from clipper.jobs import now, runner
from clipper.main import app
from clipper.media import MediaError
from clipper.mood_studio import MoodComposition, _validate_music_timing
from clipper.providers import ProviderError
from clipper.mood_quotes import validate_quotes
from clipper.mood_text import automatic_segments, normalized_words, sequence_warnings, word_count
from clipper.mood_renderer import _background_filter_chain, _video_filter_graph, validate_quote_layout
from clipper.mood_visuals import MoodVisualSettings, VISUAL_PRESETS, apply_visual_preset, recommend_visual_presets


def _quotes(suffix=""):
    texts = [
        "Bahagia tumbuh dari hal kecil yang kita syukuri." + suffix,
        "Hari biasa pun terasa hangat saat hati berhenti terburu-buru." + suffix,
        "Senyum sederhana kadang cukup mengubah arah satu hari." + suffix,
        "Kita tidak perlu menunggu sempurna untuk merasa cukup." + suffix,
        "Ada tenang yang datang saat kita hadir untuk hari ini." + suffix,
    ]
    quotes = []
    for index, text in enumerate(texts, 1):
        first, rest = text.split(" ", 1)
        quotes.append({
            "title": f"Momen sederhana {index}", "text": text,
            "segments": [{"text": first, "order": 1}, {"text": rest, "order": 2}], "mood": "kebahagiaan-sederhana",
            "tone": "natural", "visual_keywords": ["sunrise", "warm light"], "music_mood": "calm",
        })
    return {"quotes": quotes}


def run():
    with patch("clipper.main.runner.start"):
        with TestClient(app) as client:
            with patch.dict(os.environ, {"GEMINI_API_KEY": "", "OPENAI_API_KEY": ""}):
                categories = client.get("/api/mood-quotes/categories").json()
                assert len(categories["categories"]) == 8
                assert sum(len(item["subcategories"]) for item in categories["categories"]) >= 60
                assert len(categories["visual_presets"]) == 10
                assert all(item["version"] == 1 and item["effects"] and item["typography"] for item in categories["visual_presets"])
                assert len({json.dumps(item.effects.model_dump(mode="json"), sort_keys=True) for item in VISUAL_PRESETS}) >= 8
                assert categories["providers"]["default"] == "gemini"
            with patch.dict(os.environ, {"GEMINI_API_KEY": "", "OPENAI_API_KEY": "test-openai-key"}):
                assert client.get("/api/mood-quotes/categories").json()["providers"]["default"] == "openai"

            cinematic_quote = (
                "Takut gagal lagi itu wajar. Tapi kamu sudah tahu rasanya jatuh dan tetap bertahan. "
                "Bawa pengalaman itu, lalu coba sekali lagi dengan cara yang lebih bijak."
            )
            auto_segments = automatic_segments(cinematic_quote, 12)
            assert len(auto_segments) >= 2
            assert normalized_words(" ".join(item["text"] for item in auto_segments)) == normalized_words(cinematic_quote)
            assert len({item["id"] for item in auto_segments}) == len(auto_segments)
            assert auto_segments[0]["start"] == 0 and auto_segments[-1]["end"] == 12
            assert all(left["end"] == right["start"] for left, right in zip(auto_segments, auto_segments[1:]))
            multiline = "Hati tenang.\nKita mulai lagi—perlahan. ✨"
            multiline_segments = automatic_segments(multiline, 8)
            assert normalized_words(" ".join(item["text"] for item in multiline_segments)) == normalized_words(multiline)
            assert any("terlalu singkat" in warning for warning in sequence_warnings(auto_segments, 2.5))

            for indonesian in (
                "Terkadang, kita hanya perlu berhenti sejenak agar hati bisa menyusul pikiran.",
                "Dan hari ini, kita mencoba lagi dengan langkah yang lebih tenang.",
                "Karena waktu berjalan, kita belajar menerima hal yang tidak bisa diubah.",
            ):
                segments = automatic_segments(indonesian, 10)
                assert normalized_words(" ".join(item["text"] for item in segments)) == normalized_words(indonesian)
                assert all(word_count(item["text"]) > 1 for item in segments), [item["text"] for item in segments]
            complex_indonesian = (
                "Pada hari yang berat, terkadang kita berhenti sejenak agar pikiran kembali tenang. "
                "Namun, perjalanan belum selesai karena harapan masih hidup, dan kita dapat melangkah perlahan."
            )
            complex_segments = automatic_segments(complex_indonesian, 12)
            assert normalized_words(" ".join(item["text"] for item in complex_segments)) == normalized_words(complex_indonesian)
            assert all(word_count(item["text"]) > 1 for item in complex_segments)
            assert all(not item["text"].casefold().startswith(("agar ", "dan ", "karena ", "sehingga ")) for item in complex_segments)
            terkadang = automatic_segments("Terkadang, kita hanya perlu berhenti sejenak agar hati bisa menyusul pikiran.", 10)
            assert terkadang[0]["text"].casefold().startswith("terkadang, kita")
            preferred_terkadang = automatic_segments(
                "Terkadang, kita hanya perlu berhenti sejenak agar hati bisa menyusul pikiran.", 10,
                preferred=[{"text": "Terkadang,"}, {"text": "kita hanya perlu berhenti sejenak agar hati bisa menyusul pikiran."}],
            )
            assert preferred_terkadang[0]["text"].casefold().startswith("terkadang, kita")

            old_music_shape = MoodComposition.model_validate({"text": {"text": "Old single quote", "start": 0, "end": 10}})
            assert old_music_shape.music.offset == 0 and old_music_shape.music.muted is False
            valid_music_timing = {"duration": 10, "music": {
                "asset_id": "music-1", "offset": 2, "trim_start": 1, "trim_end": 5,
                "fade_in": 0.5, "fade_out": 0.5, "loop": False,
            }}
            _validate_music_timing(valid_music_timing, {"duration": 8})
            try:
                _validate_music_timing({**valid_music_timing, "music": {**valid_music_timing["music"], "offset": 9.5}}, {"duration": 8})
            except Exception as exc:
                assert "audio" in str(exc).casefold() or "musik" in str(exc).casefold()
            else:
                raise AssertionError("Music offset that leaves no audible span was accepted")
            short_loop = {**valid_music_timing, "music": {
                **valid_music_timing["music"], "loop": True, "trim_start": 1, "trim_end": 1.02,
                "fade_in": 0, "fade_out": 0,
            }}
            try:
                _validate_music_timing(short_loop, {"duration": 8})
            except Exception as exc:
                assert "0,05" in str(exc)
            else:
                raise AssertionError("Too-short looping music source was accepted")

            assert [item.id for item in recommend_visual_presets(["sedih"])] == ["sad-night", "rainy-memories", "minimal-aesthetic"]
            manual_composition = {
                "visual": MoodVisualSettings().model_dump(mode="json"),
                "background": {"kind": "image", "asset_id": "user-image", "color": "#111111", "color2": "#222222"},
                "music": {"asset_id": "user-music", "volume": 0.3},
                "text": {"text": "Quote tetap", "start": 1, "end": 8, "font": "Arial", "font_size": 40},
                "text_mode": "sequential", "segments_source": "manual",
                "segments": [{"id": "s1", "text": "Teks manual", "start": 1, "end": 8, "animation": "slide_up", "animation_duration": 0.5}],
            }
            styled = apply_visual_preset(manual_composition, "golden-hour")
            assert styled["text"]["text"] == "Quote tetap" and styled["text"]["start"] == 1 and styled["text"]["end"] == 8
            assert styled["background"]["asset_id"] == "user-image" and styled["music"]["asset_id"] == "user-music"
            assert styled["segments"] == manual_composition["segments"]
            assert styled["text"]["font"] == "Georgia" and styled["visual"]["preset_id"] == "golden-hour"
            assert manual_composition["visual"]["preset_id"] is None
            auto_composition = {**manual_composition, "segments_source": "auto"}
            auto_styled = apply_visual_preset(auto_composition, "golden-hour")
            assert auto_styled["segments"][0]["start"] == 1 and auto_styled["segments"][0]["end"] == 8
            assert auto_styled["segments"][0]["animation"] == "fade_up"

            filters_comp = {
                "background": {"kind": "video"},
                "visual": MoodVisualSettings(motion="ken_burns", motion_intensity="strong", brightness=-0.1,
                    contrast=1.1, saturation=0.8, temperature=0.4, vignette=0.5, grain=3, dark_overlay=0.2).model_dump(mode="json"),
            }
            filter_chain = _background_filter_chain(filters_comp, 720, 1280, 10)
            assert "zoompan=" in filter_chain and "s=720x1280" in filter_chain
            assert all(name in filter_chain for name in ("eq=", "colorbalance=", "vignette=", "noise=", "drawbox="))
            graph = _video_filter_graph(filters_comp, Path("render.ass"), 720, 1280, 10, gradient_index=2, text_gradient_index=3)
            assert "[2:v]" in graph and "[3:v]" in graph and "ass='" in graph and "[vout]" in graph
            assert 720 / 1280 == 1080 / 1920 == 9 / 16
            for preset in VISUAL_PRESETS:
                validate_quote_layout("Kita tetap bertumbuh melalui langkah sederhana.", {"text": preset.typography.model_dump(mode="json")})
            try:
                validate_quote_layout("kata " * 400, {"text": {"font_size": 120, "x": 5, "y": 8, "line_spacing": 2.2}})
            except ValueError:
                pass
            else:
                raise AssertionError("Unsafe quote layout was accepted")
            try:
                MoodVisualSettings(grain=11)
            except Exception:
                pass
            else:
                raise AssertionError("Out-of-range grain value was accepted")

            created = client.post("/api/mood-projects", json={"title": "Test Mood"})
            assert created.status_code == 200, created.text
            project_id = created.json()["project"]["id"]
            fresh_composition = created.json()["project"]["composition"]
            assert fresh_composition["text_mode"] == "sequential" and fresh_composition["segments"] == []
            assert fresh_composition["music"]["offset"] == 0 and fresh_composition["music"]["muted"] is False
            legacy_project = client.post("/api/mood-projects", json={"title": "Legacy draft"}).json()["project"]["id"]
            legacy_composition = dict(fresh_composition)
            legacy_composition.pop("text_mode"); legacy_composition.pop("segments"); legacy_composition.pop("segments_source")
            legacy_composition["text"] = {key: value for key, value in legacy_composition["text"].items() if key not in {"gradient_opacity", "auto_contrast"}}
            legacy_composition["text"]["text"] = "Draft lama tetap satu quote."
            legacy_composition["text"]["end"] = 10
            legacy_saved = client.patch(f"/api/mood-projects/{legacy_project}", json={"composition": legacy_composition})
            assert legacy_saved.status_code == 200 and legacy_saved.json()["project"]["composition"]["text_mode"] == "single"
            assert legacy_saved.json()["project"]["composition"]["text"]["text"] == "Draft lama tetap satu quote."
            assert legacy_saved.json()["project"]["composition"]["visual"]["schema_version"] == 1
            assert legacy_saved.json()["project"]["composition"]["visual"]["motion"] == "none"
            assert legacy_saved.json()["project"]["composition"]["text"]["font_weight"] == 600
            assert legacy_saved.json()["project"]["composition"]["music"]["offset"] == 0
            topic_saved = client.patch(f"/api/mood-projects/{project_id}", json={"custom_topic": "Semangat menghadapi interview kerja"})
            assert topic_saved.status_code == 200
            missing_consent = client.post(f"/api/mood-projects/{project_id}/generate", json={"provider": "gemini", "consent": False})
            assert missing_consent.status_code == 400
            with patch.dict(os.environ, {"GEMINI_API_KEY": "", "OPENAI_API_KEY": ""}):
                unavailable = client.post(f"/api/mood-projects/{project_id}/generate", json={"provider": "gemini", "consent": True})
            assert unavailable.status_code == 503 and "fallback" in unavailable.json()["detail"]

            prompts = []

            def fake_analyze(provider, prompt, _schema, _name):
                prompts.append((provider, prompt))
                return json.dumps(_quotes(), ensure_ascii=False), "gemini-test", {"promptTokenCount": 64, "candidatesTokenCount": 400}

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch("clipper.mood_quotes.analyze", side_effect=fake_analyze):
                generated = client.post(f"/api/mood-projects/{project_id}/generate", json={"provider": "gemini", "consent": True})
            assert generated.status_code == 200, generated.text
            first = generated.json()
            assert len(first["quotes"]) == 5 and first["provider"] == "gemini"
            assert [segment["order"] for segment in first["quotes"][0]["segments"]] == [1, 2]
            assert "bahagia" in prompts[0][1] and "kebahagiaan-sederhana" in prompts[0][1]
            assert "Semangat menghadapi interview kerja" in prompts[0][1]
            assert "Klipnara API key" not in prompts[0][1]

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "OPENAI_API_KEY": "other-test-key"}), patch(
                "clipper.mood_quotes.analyze", side_effect=ProviderError("Gemini Free Tier quota/rate limit exceeded (HTTP 429).")
            ) as provider_call:
                quota = client.post(f"/api/mood-projects/{project_id}/generate", json={"provider": "gemini", "consent": True})
            assert quota.status_code == 502 and provider_call.call_count == 1 and "429" in quota.json()["detail"]

            english_project = client.post("/api/mood-projects", json={"title": "English story"}).json()["project"]["id"]
            varied = client.patch(f"/api/mood-projects/{english_project}", json={
                "category_id": "cinta-hubungan", "subcategory_id": "patah-hati", "tone": "poetic",
                "perspective": "aku", "length": "storytelling", "language": "english",
            })
            assert varied.status_code == 200
            english_batch = _quotes()
            for item in english_batch["quotes"]:
                item["mood"], item["tone"] = "patah-hati", "poetic"
            openai_calls = []
            def fake_openai(provider, prompt, _schema, _name):
                openai_calls.append((provider, prompt))
                return json.dumps(english_batch, ensure_ascii=False), "openai-test", {"prompt_tokens": 70, "completion_tokens": 350}
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}), patch("clipper.mood_quotes.analyze", side_effect=fake_openai):
                english = client.post(f"/api/mood-projects/{english_project}/generate", json={"provider": "openai", "consent": True})
            assert english.status_code == 200 and english.json()["provider"] == "openai"
            assert "Write exactly 5" in openai_calls[0][1] and "about 25–40 seconds" in openai_calls[0][1] and "point of view Aku" in openai_calls[0][1]

            favorite = client.post(f"/api/mood-projects/{project_id}/favorites", json={"quote": first["quotes"][0], "generation_id": first["id"]})
            assert favorite.status_code == 200
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch("clipper.mood_quotes.analyze", return_value=(json.dumps(_quotes(" hari ini"), ensure_ascii=False), "gemini-test", {})):
                regenerated = client.post(f"/api/mood-projects/{project_id}/generate", json={"provider": "gemini", "consent": True})
            assert regenerated.status_code == 200 and len(regenerated.json()["quotes"]) == 5
            detail = client.get(f"/api/mood-projects/{project_id}").json()
            assert len(detail["generations"]) == 2 and len(detail["favorites"]) == 1

            malformed = client.post(f"/api/mood-projects/{project_id}/generate", json={"provider": "gemini", "consent": True})
            assert malformed.status_code == 503  # Key is no longer configured; no silent provider switch.
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), patch("clipper.mood_quotes.analyze", return_value=("not-json", "gemini-test", {})):
                malformed = client.post(f"/api/mood-projects/{project_id}/generate", json={"provider": "gemini", "consent": True})
            assert malformed.status_code == 502
            assert len(client.get(f"/api/mood-projects/{project_id}/generations").json()) == 2

            duplicated = _quotes()
            duplicated["quotes"][1]["text"] = duplicated["quotes"][0]["text"]
            duplicated["quotes"][1]["segments"] = [{"text": duplicated["quotes"][1]["text"], "order": 1}]
            try:
                validate_quotes(duplicated, category_id="bahagia-positif", subcategory_id="kebahagiaan-sederhana", tone_id="natural")
            except ValueError as exc:
                assert "mirip" in str(exc)
            else:
                raise AssertionError("Near-duplicate quotes were accepted")

            selected = first["quotes"][0]
            selected = {**selected, "text": cinematic_quote, "segments": [{"text": cinematic_quote, "order": 1}]}
            composition = detail["project"]["composition"]
            composition.update({"duration": 12, "text_mode": "sequential", "segments": auto_segments, "segments_source": "auto"})
            composition["visual"].update({"preset_id": "vintage-memories", "motion": "slow_zoom_in", "grain": 4})
            composition["text"].update({"text": " ".join(item["text"] for item in auto_segments), "start": 0, "end": 12})
            saved = client.patch(f"/api/mood-projects/{project_id}", json={"selected_quote": selected, "composition": composition})
            assert saved.status_code == 200 and saved.json()["project"]["selected_quote"]["text"] == selected["text"]
            restored = client.get(f"/api/mood-projects/{project_id}").json()["project"]["composition"]
            assert restored["text_mode"] == "sequential" and restored["segments"] == auto_segments
            assert restored["visual"] == composition["visual"]
            invalid_sequence = json.loads(json.dumps(restored))
            invalid_sequence["segments"][1]["start"] = invalid_sequence["segments"][0]["end"] - 0.2
            assert client.patch(f"/api/mood-projects/{project_id}", json={"composition": invalid_sequence}).status_code == 422
            duplicate_sequence = json.loads(json.dumps(restored))
            duplicate_sequence["segments"][1]["id"] = duplicate_sequence["segments"][0]["id"]
            assert client.patch(f"/api/mood-projects/{project_id}", json={"composition": duplicate_sequence}).status_code == 422
            manual_sequence = json.loads(json.dumps(restored))
            manual_sequence["segments"][0]["text"] += " (edit manual)"
            manual_sequence["segments_source"] = "manual"
            manual_sequence["text"]["text"] = " ".join(item["text"] for item in manual_sequence["segments"])
            manually_saved = client.patch(f"/api/mood-projects/{project_id}", json={"composition": manual_sequence})
            assert manually_saved.status_code == 200
            assert manually_saved.json()["project"]["composition"]["segments_source"] == "manual"
            assert manually_saved.json()["project"]["composition"]["segments"][0]["id"] == auto_segments[0]["id"]
            saved = manually_saved

            with patch("clipper.mood_studio._probe_asset", return_value={"duration": None, "width": 640, "height": 640, "has_audio": False}):
                upload = client.post(f"/api/mood-projects/{project_id}/assets", data={"kind": "background_image"}, files={"file": ("soft.png", BytesIO(b"image fixture"), "image/png")})
            assert upload.status_code == 200, upload.text
            asset = upload.json()
            bad_upload = client.post(f"/api/mood-projects/{project_id}/assets", data={"kind": "background_image"}, files={"file": ("bad.gif", BytesIO(b"no"), "image/gif")})
            assert bad_upload.status_code == 415
            with patch("clipper.mood_studio._probe_asset", return_value={"duration": 12.0, "width": 360, "height": 640, "has_audio": True}):
                video_asset = client.post(f"/api/mood-projects/{project_id}/assets", data={"kind": "background_video"}, files={"file": ("background.mp4", BytesIO(b"video fixture"), "video/mp4")})
            with patch("clipper.mood_studio._probe_asset", return_value={"duration": 5.0, "width": None, "height": None, "has_audio": True}):
                music_asset = client.post(f"/api/mood-projects/{project_id}/assets", data={"kind": "music"}, files={"file": ("music.wav", BytesIO(b"audio fixture"), "audio/wav")})
            assert video_asset.status_code == 200 and video_asset.json()["has_audio"] is True
            assert music_asset.status_code == 200 and music_asset.json()["kind"] == "music"

            def fake_thumbnail_ffmpeg(args, **_kwargs):
                Path(args[-1]).write_bytes(b"thumbnail fixture")
                return SimpleNamespace(stdout="", stderr="", returncode=0)

            with patch("clipper.mood_studio.executable", return_value="ffmpeg"), patch("clipper.mood_studio.subprocess.run", side_effect=fake_thumbnail_ffmpeg) as extract:
                thumbnail = client.get(f"/api/mood-assets/{video_asset.json()['id']}/thumbnail?time=1.2")
                cached_thumbnail = client.get(f"/api/mood-assets/{video_asset.json()['id']}/thumbnail?time=1.2")
            assert thumbnail.status_code == 200 and thumbnail.content == b"thumbnail fixture"
            assert cached_thumbnail.status_code == 200 and extract.call_count == 1
            assert client.get(f"/api/mood-assets/{video_asset.json()['id']}/thumbnail?time=30").status_code == 422

            source_id = uuid.uuid4().hex
            source_path = SOURCE_DIR / "mood-source-library-fixture.mp4"
            source_path.write_bytes(b"source library fixture")
            with connect() as conn:
                conn.execute("INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,audio_codec,sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                             (source_id, source_path.name, str(source_path.resolve()), source_path.stat().st_size, 15, 720, 1280, "h264", "aac", "sourcehash", now()))
            linked = client.post(f"/api/mood-projects/{project_id}/source-assets", json={"source_id": source_id})
            assert linked.status_code == 200 and linked.json()["source_id"] == source_id
            assert client.delete(f"/api/sources/{source_id}").status_code == 409

            composition = saved.json()["project"]["composition"]
            composition["background"].update({"kind": "image", "asset_id": asset["id"]})
            composition["music"].update({
                "asset_id": music_asset.json()["id"], "offset": 2, "trim_start": 1, "trim_end": 5,
                "volume": 0.3, "fade_in": 0.5, "fade_out": 0.5, "loop": False, "muted": False,
            })
            queued = client.post(f"/api/mood-projects/{project_id}/render", json=composition)
            assert queued.status_code == 200, queued.text
            with connect() as conn:
                snapshot = json.loads(conn.execute("SELECT options_json FROM mood_jobs WHERE id=?", (queued.json()["id"],)).fetchone()[0])
            assert snapshot["composition"]["music"]["offset"] == 2
            assert snapshot["composition"]["music"]["trim_start"] == 1
            assert snapshot["composition"]["music"]["muted"] is False

            def fake_render(*, render_id, **_kwargs):
                path = CLIP_DIR / f"mood-{render_id}.mp4"
                path.write_bytes(b"synthetic approved MP4")
                return path

            class StopWorker(Exception):
                pass

            with patch("clipper.jobs.render_mood_video", side_effect=fake_render), \
                 patch("clipper.jobs.time.sleep", side_effect=StopWorker), \
                 patch("clipper.youtube.next_due_publication", return_value=None):
                try:
                    runner._run()
                except StopWorker:
                    pass
            status = client.get(f"/api/mood-jobs/{queued.json()['id']}").json()
            assert status["status"] == "completed" and status["progress"] == 1
            with patch("clipper.mood_studio.probe", return_value={"video_codec": "h264", "audio_codec": "aac", "duration": 8, "width": 720, "height": 1280}):
                approved = client.post(f"/api/mood-renders/{queued.json()['render_id']}/review", json={"status": "approved"})
            assert approved.status_code == 200 and approved.json()["review_status"] == "approved"
            approved_detail = client.get(f"/api/mood-projects/{project_id}").json()
            unchanged = client.patch(f"/api/mood-projects/{project_id}", json={
                "selected_quote": approved_detail["project"]["selected_quote"],
                "composition": approved_detail["project"]["composition"],
            })
            assert unchanged.status_code == 200
            assert unchanged.json()["project"]["current_render"]["status"] == "completed"
            assert unchanged.json()["project"]["current_render"]["review_status"] == "approved"
            listing = client.get("/api/jobs").json()
            assert any(item["kind"] == "mood_render" and item["source_name"] == "Test Mood" for item in listing)

            next_render = client.post(f"/api/mood-projects/{project_id}/render", json=composition).json()
            cancelled = client.post(f"/api/mood-jobs/{next_render['id']}/cancel")
            assert cancelled.status_code == 200
            with connect() as conn:
                state = conn.execute("SELECT status FROM mood_renders WHERE id=?", (next_render["render_id"],)).fetchone()[0]
            assert state == "cancelled"
            retried = client.post(f"/api/mood-jobs/{next_render['id']}/retry")
            assert retried.status_code == 200
            assert client.post(f"/api/mood-jobs/{retried.json()['id']}/cancel").status_code == 200

            active_render = client.post(f"/api/mood-projects/{project_id}/render", json=composition).json()
            render_started, worker_stopped = threading.Event(), threading.Event()

            def blocking_render(*, progress, cancel, **_kwargs):
                progress(0.4)
                render_started.set()
                assert cancel.wait(10), "worker cancellation was not delivered"
                raise MediaError("Mood Quotes render dibatalkan.")

            def stop_worker():
                try:
                    runner._run()
                except StopWorker:
                    pass
                finally:
                    worker_stopped.set()

            with patch("clipper.jobs.render_mood_video", side_effect=blocking_render), patch("clipper.jobs.time.sleep", side_effect=StopWorker):
                worker = threading.Thread(target=stop_worker, daemon=True)
                worker.start()
                assert render_started.wait(10)
                assert client.get(f"/api/mood-jobs/{active_render['id']}").json()["progress"] == 0.4
                assert client.post(f"/api/mood-jobs/{active_render['id']}/cancel").status_code == 200
                assert worker_stopped.wait(10)
            assert client.get(f"/api/mood-jobs/{active_render['id']}").json()["status"] == "cancelled"

            used_asset = client.delete(f"/api/mood-projects/{project_id}/assets/{asset['id']}")
            assert used_asset.status_code == 409
            solid = composition.copy()
            solid["background"] = {**solid["background"], "kind": "solid", "asset_id": None}
            updated = client.patch(f"/api/mood-projects/{project_id}", json={"composition": solid})
            assert updated.status_code == 200
            assert client.delete(f"/api/mood-projects/{project_id}/assets/{asset['id']}").status_code == 200

            legacy_source, legacy_job, legacy_clip = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
            with connect() as conn:
                conn.execute("INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                             (legacy_source, "old.mp4", "missing.mp4", 1, 20, 720, 1280, "h264", "hash", now()))
                conn.execute("INSERT INTO jobs(id,source_id,kind,status,phase,options_json,created_at,updated_at) VALUES(?,?,?,'failed','failed','{}',?,?)",
                             (legacy_job, legacy_source, "render", now(), now()))
                conn.execute("INSERT INTO clips(id,source_id,job_id,start,end,title,reason,rank,edit_json,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,'ready',?)",
                             (legacy_clip, legacy_source, legacy_job, 0, 10, "Old clip", "fixture", 1, "{}", now()))
            init_db()
            with connect() as conn:
                assert conn.execute("SELECT title FROM clips WHERE id=?", (legacy_clip,)).fetchone()[0] == "Old clip"
                assert conn.execute("SELECT count(*) FROM mood_projects WHERE id=?", (project_id,)).fetchone()[0] == 1

            with connect() as conn:
                conn.execute("UPDATE mood_jobs SET status='failed' WHERE id=?", (retried.json()["id"],))
                conn.execute("UPDATE mood_renders SET status='failed' WHERE id=?", (retried.json()["render_id"],))
            with patch("clipper.mood_studio.probe", return_value={"video_codec": "h264", "audio_codec": "aac", "duration": 8, "width": 720, "height": 1280}):
                assert client.delete(f"/api/mood-projects/{project_id}").status_code == 200
            with connect() as conn:
                assert conn.execute("SELECT count(*) FROM sources WHERE id=?", (legacy_source,)).fetchone()[0] == 1
                assert conn.execute("SELECT count(*) FROM sources WHERE id=?", (source_id,)).fetchone()[0] == 1
                assert conn.execute("SELECT count(*) FROM mood_projects WHERE id=?", (project_id,)).fetchone()[0] == 0
            assert source_path.is_file()
            assert client.delete(f"/api/sources/{source_id}").status_code == 200
            assert not source_path.exists()
            print("Mood quote consent/schema/history/favorites/drafts/assets/jobs/review and additive migration checks passed")


if __name__ == "__main__":
    run()
