"""Render synthetic Mood Quotes backgrounds/audio locally; no AI or user media is used."""

import atexit
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

data_dir = Path(tempfile.mkdtemp(prefix="klipnara-mood-e2e-"))
atexit.register(shutil.rmtree, data_dir, ignore_errors=True)
os.environ["CLIPPER_DATA_DIR"] = str(data_dir)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipper.config import CLIP_DIR, WORK_DIR
from clipper.media import MediaError, executable, probe
from clipper.mood_renderer import _audio_mean_volume, render_mood_video


def _run(args):
    subprocess.run(args, capture_output=True, text=True, timeout=120, check=True)


def _composition(background, music=None):
    return {
        "resolution": "720", "fps": 30, "duration": 4,
        "background": {"kind": background, "asset_id": None, "color": "#192c38", "color2": "#8d536d",
                       "video_start": 0, "loop": True, "mute_audio": background != "video", "audio_volume": 0.15},
        "music": {"asset_id": music, "trim_start": 0, "trim_end": 2, "volume": 0.2, "fade_in": 0.3, "fade_out": 0.5, "loop": True},
        "text": {"text": "Bahagia {sederhana}, café.\nHari ini.", "font": "Georgia", "font_size": 38,
                  "color": "#ffffff", "alignment": "center", "x": 50, "y": 53, "line_spacing": 1.3,
                  "shadow": True, "outline": False, "opacity": 96, "start": 0.2, "end": 3.8,
                   "animation_in": "typewriter", "animation_out": "fade", "animation_duration": 0.8,
                   "gradient_opacity": 18, "auto_contrast": False},
        "visual": {"schema_version": 1, "preset_id": None, "motion": "none", "motion_intensity": "subtle",
                   "brightness": 0, "contrast": 1, "saturation": 1, "temperature": 0, "vignette": 0,
                   "grain": 0, "dark_overlay": 0, "gradient_top": "#26344a", "gradient_bottom": "#101820",
                   "gradient_overlay_opacity": 0, "segment_animation": "fade_up"},
    }


def main():
    ffmpeg = executable("ffmpeg", "FFMPEG_PATH")
    ffprobe = executable("ffprobe", "FFPROBE_PATH")
    media_dir = Path(tempfile.mkdtemp(prefix="klipnara-mood-media-"))
    atexit.register(shutil.rmtree, media_dir, ignore_errors=True)
    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    video = media_dir / "synthetic-background.mp4"
    silent_video = media_dir / "synthetic-silent-background.mp4"
    silent_audio_video = media_dir / "synthetic-background-silent-audio.mp4"
    music = media_dir / "synthetic-music.wav"
    silent_music = media_dir / "synthetic-silent-music.wav"
    image = media_dir / "synthetic-image.png"
    _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=24",
          "-f", "lavfi", "-i", "sine=frequency=420:sample_rate=48000", "-t", "1.5", "-c:v", "libx264", "-preset", "ultrafast",
          "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)])
    _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=44100",
          "-t", "2", "-ac", "1", "-c:a", "pcm_s16le", str(music)])
    _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=48000",
          "-t", "2", "-c:a", "pcm_s16le", str(silent_music)])
    _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=24",
          "-t", "1.5", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(silent_video)])
    _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=24",
          "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-t", "1.5", "-c:v", "libx264",
          "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(silent_audio_video)])
    _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x304c3d:s=360x640", "-frames:v", "1", str(image)])
    assets = {
        "video": {"kind": "background_video", "path": str(video), "duration": 1.5, "has_audio": True},
        "silent_video": {"kind": "background_video", "path": str(silent_video), "duration": 1.5, "has_audio": False},
        "silent_audio_video": {"kind": "background_video", "path": str(silent_audio_video), "duration": 1.5, "has_audio": True},
        "music": {"kind": "music", "path": str(music), "duration": 2, "has_audio": True},
        "silent_music": {"kind": "music", "path": str(silent_music), "duration": 2, "has_audio": True},
        "image": {"kind": "background_image", "path": str(image), "duration": None, "has_audio": False},
    }
    sequential = _composition("gradient")
    sequential.update({"text_mode": "sequential", "segments_source": "auto", "segments": [
        {"id": "hook", "text": "Bahagia tumbuh dari hal kecil.", "start": 0, "end": 1.8, "animation": "fade_up", "animation_duration": 0.4},
        {"id": "close", "text": "Kita mulai lagi—perlahan. ✨", "start": 1.8, "end": 4, "animation": "gentle_scale", "animation_duration": 0.45},
    ]})
    music_only = _composition("solid", "music")
    music_only["music"].update({"trim_start": 0.25, "trim_end": 1.75})
    music_nonloop = _composition("solid", "music")
    music_nonloop["music"].update({"loop": False, "trim_start": 0.25, "trim_end": 1.75, "fade_out": 0.4})
    cinematic_video = _composition("video", "music")
    cinematic_video["visual"].update({"motion": "ken_burns", "motion_intensity": "subtle", "brightness": -0.06,
                                       "contrast": 1.1, "saturation": 0.82, "temperature": 0.25, "vignette": 0.35,
                                       "grain": 2, "dark_overlay": 0.08, "gradient_overlay_opacity": 12})
    cinematic_image = _composition("image")
    cinematic_image["visual"].update({"motion": "pan_left", "motion_intensity": "normal", "vignette": 0.2,
                                       "gradient_top": "#56436d", "gradient_bottom": "#1c2638", "gradient_overlay_opacity": 14})
    cases = [
        ("short-looped-video-mixed-audio", _composition("video", "music"), {"video": assets["video"], "music": assets["music"]}),
        ("background-audio-only", _composition("video"), {"video": assets["video"]}),
        ("music-only-resample-loop-trim-fades", music_only, {"music": assets["music"]}),
        ("music-shorter-than-video-no-loop-fade", music_nonloop, {"music": assets["music"]}),
        ("music-volume-zero-explicit-silence", {**_composition("solid", "music"), "music": {**_composition("solid", "music")["music"], "volume": 0}}, {"music": assets["music"]}),
        ("muted-background-silent-aac", {**_composition("video"), "background": {**_composition("video")["background"], "mute_audio": True}}, {"video": assets["video"]}),
        ("background-audio-volume-zero-silent-aac", {**_composition("video"), "background": {**_composition("video")["background"], "audio_volume": 0}}, {"video": assets["video"]}),
        ("silent-background-silent-aac", {**_composition("video"), "background": {**_composition("video")["background"], "mute_audio": False}}, {"silent_video": assets["silent_video"]}),
        ("solid-silent-aac", _composition("solid"), {}),
        ("gradient-silent-aac", _composition("gradient"), {}),
        ("still-image-silent-aac", _composition("image"), {"image": assets["image"]}),
        ("cinematic-video-motion-grade-with-music", cinematic_video, {"silent_video": assets["silent_video"], "music": assets["music"]}),
        ("cinematic-image-pan-overlay-silent-aac", cinematic_image, {"image": assets["image"]}),
        ("sequential-unicode-text", sequential, {}),
    ]
    corrupt_music = media_dir / "corrupt.wav"
    corrupt_music.write_bytes(b"not an audio file")
    try:
        render_mood_video(render_id=uuid.uuid4().hex, quote={"text": "test", "segments": []},
                          composition=_composition("solid", "music"), assets={"music": {"kind": "music", "path": str(corrupt_music), "duration": 2}},
                          cancel=threading.Event(), progress=lambda _value: None)
    except MediaError as exc:
        assert "memeriksa sinyal audio" in str(exc)
    else:
        raise AssertionError("Corrupted selected music was accepted")
    try:
        render_mood_video(render_id=uuid.uuid4().hex, quote={"text": "test", "segments": []},
                          composition=_composition("solid", "music"), assets={"music": assets["silent_music"]},
                          cancel=threading.Event(), progress=lambda _value: None)
    except MediaError as exc:
        assert "File musik terpilih senyap" in str(exc)
    else:
        raise AssertionError("Selected silent music was accepted")
    try:
        render_mood_video(render_id=uuid.uuid4().hex, quote={"text": "test", "segments": []},
                          composition=_composition("video"), assets={"video": assets["silent_audio_video"]},
                          cancel=threading.Event(), progress=lambda _value: None)
    except MediaError as exc:
        assert "Audio background video senyap" in str(exc)
    else:
        raise AssertionError("Selected silent background audio was accepted")
    results = []
    for name, composition, selected_assets in cases:
        background_key = next((key for key, item in selected_assets.items() if item["kind"] == "background_video"), None)
        if background_key:
            composition["background"]["asset_id"] = background_key
        elif composition["background"]["kind"] == "image":
            composition["background"]["asset_id"] = "image"
        if composition["music"]["asset_id"]:
            composition["music"]["asset_id"] = "music"
        render_id, progress = uuid.uuid4().hex, []
        started = time.perf_counter()
        output = render_mood_video(
            render_id=render_id,
            quote={"text": composition["text"]["text"], "segments": [
                {"text": "Bahagia {sederhana}, café.", "order": 1}, {"text": "Hari ini.", "order": 2},
            ]},
            composition=composition,
            assets=selected_assets,
            cancel=threading.Event(),
            progress=progress.append,
        )
        metadata = probe(output)
        _run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(output)])
        assert metadata["video_codec"] == "h264" and metadata["audio_codec"] == "aac", metadata
        assert (metadata["width"], metadata["height"]) == (720, 1280), metadata
        assert abs(metadata["duration"] - 4) < 0.2, metadata
        assert progress and output.stat().st_size > 0
        output_mean = _audio_mean_volume(ffmpeg, output, 0, 4)
        if composition["music"].get("asset_id") and composition["music"]["volume"] > 0 or any(item.get("has_audio") for item in selected_assets.values()) and not composition["background"].get("mute_audio") and composition["background"]["audio_volume"] > 0:
            assert math.isfinite(output_mean) and output_mean > -90, (name, output_mean)
        else:
            assert not math.isfinite(output_mean) or output_mean <= -90, (name, output_mean)
        results.append({"case": name, "duration_seconds": round(metadata["duration"], 3), "bytes": output.stat().st_size,
                        "elapsed_seconds": round(time.perf_counter() - started, 2), "video_codec": metadata["video_codec"],
                        "audio_codec": metadata["audio_codec"], "audio_mean_db": output_mean if math.isfinite(output_mean) else None,
                        "resolution": f"{metadata['width']}x{metadata['height']}"})
    print(json.dumps({"source_media": "synthetic FFmpeg test patterns and sine waves", "ai_calls": 0, "outputs": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
