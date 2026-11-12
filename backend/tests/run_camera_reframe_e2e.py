"""Opt-in local E2E for 16:9 subject movement through Dynamic Reframing."""

import argparse
import os
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import patch
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    os.environ["CLIPPER_DATA_DIR"] = str(args.output_dir / "appdata")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from fastapi.testclient import TestClient

    from clipper.config import CLIP_DIR
    from clipper.db import connect
    from clipper.jobs import runner
    from clipper.main import app
    from clipper.media import executable, probe

    ffmpeg = executable("ffmpeg", "FFMPEG_PATH")
    suffix = uuid.uuid4().hex[:8]
    source_path = args.output_dir / f"camera-moving-16x9-{suffix}.mp4"
    output_path = args.output_dir / f"camera-reframed-{suffix}.mp4"
    move_right, move_left = "((t-2)/4)", "((t-6)/4)"
    smooth_right = f"{move_right}*{move_right}*(3-2*{move_right})"
    smooth_left = f"{move_left}*{move_left}*(3-2*{move_left})"
    move_subject = f"if(lt(t,2),890,if(lt(t,6),890+770*{smooth_right},if(lt(t,10),1660-1530*{smooth_left},130)))"
    move_subject_y = f"if(lt(t,2),460,if(lt(t,6),460-260*{smooth_right},if(lt(t,10),200+400*{smooth_left},600)))"
    subprocess.run([
        ffmpeg, "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i",
        "color=c=0x53725d:s=1920x1080:r=30:d=12", "-f", "lavfi", "-i",
        "color=c=0xe3ba55:s=140x160:r=30:d=12", "-filter_complex",
        f"[0:v][1:v]overlay=x='{move_subject}':y='{move_subject_y}':shortest=1",
        "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(source_path),
    ], check=True, capture_output=True)

    with patch("clipper.main.runner.start"):
        with TestClient(app) as client:
            with source_path.open("rb") as source_file:
                uploaded = client.post("/api/sources/upload", files={"file": (source_path.name, source_file, "video/mp4")})
            assert uploaded.status_code == 200, uploaded.text
            clip_response = client.post(f"/api/sources/{uploaded.json()['id']}/quick-clips", json={
                "title": "Moving subject reframe", "start": 0, "end": 12, "resolution": "720",
            })
            assert clip_response.status_code == 200, clip_response.text
            clip_id = clip_response.json()["clip_id"]
            edit = {
                "scene_mode": "multi",
                "scenes": [
                    {"id": "scene-left", "source_start": 0.1, "source_end": 4, "order": 0, "role": "hook"},
                    {"id": "scene-right", "source_start": 4, "source_end": 8, "order": 1, "role": "body"},
                    {"id": "scene-return", "source_start": 8, "source_end": 11.9, "order": 2, "role": "ending"},
                ],
                "transitions": {
                    "scene-left>scene-right": {"type": "crossfade", "timing_mode": "overlap", "duration": 0.3},
                    "scene-right>scene-return": {"type": "crossfade", "timing_mode": "overlap", "duration": 0.3},
                },
                "camera": {"enabled": True, "interpolation": "smooth", "scenes": {
                    "scene-left": {"keyframes": [
                        {"id": "left-start", "frame": 0, "x": 50, "y": 50, "zoom": 1},
                        {"id": "left-center", "frame": 57, "x": 50, "y": 50, "zoom": 1},
                        {"id": "left-end", "frame": 116, "x": 77, "y": 0, "zoom": 1.1},
                    ]},
                    "scene-right": {"keyframes": [
                        {"id": "right-start", "frame": 0, "x": 77, "y": 0, "zoom": 1.1},
                        {"id": "right-end", "frame": 60, "x": 100, "y": 0, "zoom": 1.5},
                        {"id": "right-track", "frame": 110, "x": 59, "y": 34, "zoom": 1.5},
                        {"id": "right-return", "frame": 119, "x": 50, "y": 35, "zoom": 1.5},
                    ]},
                    "scene-return": {"keyframes": [
                        {"id": "return-start", "frame": 0, "x": 50, "y": 35, "zoom": 1.5},
                        {"id": "return-end", "frame": 60, "x": 0, "y": 90, "zoom": 1.5},
                        {"id": "return-hold", "frame": 116, "x": 0, "y": 90, "zoom": 1.5},
                    ]},
                }},
                "subtitle_enabled": True,
                "subtitle_mode": "manual",
                "subtitle_timebase": "source",
                "subtitle_segments": [
                    {"id": "caption-one", "start": 2.2, "end": 3, "text": "Synthetic left-to-right caption"},
                    {"id": "caption-two", "start": 5.2, "end": 6.2, "text": "Synthetic return caption"},
                ],
                "title_overlay": {"enabled": True, "text": "CAMERA TEST", "size": 48, "position": 18, "duration": 3},
                "resolution": "720",
            }
            saved = client.patch(f"/api/clips/{clip_id}", json=edit)
            assert saved.status_code == 200, saved.text
            reloaded = client.get(f"/api/clips/{clip_id}").json()["clip"]["edit"]
            assert reloaded["camera"] == edit["camera"] and reloaded["subtitle_segments"] == edit["subtitle_segments"]
            assert reloaded["scenes"] == edit["scenes"] and reloaded["title_overlay"]["text"] == "CAMERA TEST"

            for resolution in ("720", "1080"):
                if resolution != "720":
                    changed = client.patch(f"/api/clips/{clip_id}", json={"resolution": resolution})
                    assert changed.status_code == 200, changed.text
                    with connect() as conn:
                        freshness = conn.execute("SELECT status,review_status,reviewed_render_sha256 FROM clips WHERE id=?", (clip_id,)).fetchone()
                    assert tuple(freshness) == ("needs_render", "needs_review", None), tuple(freshness)
                    assert client.get(f"/api/clips/{clip_id}").json()["clip"]["edit"]["resolution"] == resolution

                render_response = client.post(f"/api/clips/{clip_id}/render")
                assert render_response.status_code == 200, render_response.text
                with connect() as conn:
                    job = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (render_response.json()["id"],)).fetchone())
                runner._process(job, threading.Event())
                with connect() as conn:
                    rendered = conn.execute("SELECT rendered_path,status,review_status,reviewed_render_sha256 FROM clips WHERE id=?", (clip_id,)).fetchone()
                assert tuple(rendered[1:]) == ("completed", "needs_review", None), tuple(rendered)
                final = Path(rendered["rendered_path"])
                assert final.is_file()
                metadata = probe(final)
                width, height = (720, 1280) if resolution == "720" else (1080, 1920)
                assert (metadata["width"], metadata["height"]) == (width, height), metadata
                assert abs(metadata["duration"] - 11.2) < 0.3, metadata["duration"]

                def frame_at(second):
                    return subprocess.run([
                        ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", str(second), "-i", str(final),
                        "-vf", "format=rgb24", "-frames:v", "1", "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
                    ], check=True, capture_output=True).stdout

                expected_camera_frames = (
                    (1.9, 960, 540, 50, 50, 1),
                    (5.6, 1730, 280, 100, 0, 1.5),
                    (9.3, 200, 680, 0, 90, 1.5),
                )
                for second, subject_x, subject_y, camera_x, camera_y, zoom in expected_camera_frames:
                    frame = frame_at(second)
                    assert len(frame) == width * height * 3, (resolution, second, len(frame))
                    edges = [(x, y) for x in range(0, width, max(1, width // 80)) for y in (0, height - 1)]
                    edges += [(x, y) for y in range(0, height, max(1, height // 80)) for x in (0, width - 1)]
                    for x, y in edges:
                        offset = (y * width + x) * 3
                        assert sum(frame[offset:offset + 3]) > 120, (resolution, second, x, y, frame[offset:offset + 3])
                    subject_points = [
                        (x, y) for y in range(height // 5, height * 4 // 5)
                        for x in range(width // 4, width * 3 // 4)
                        if frame[(y * width + x) * 3] > 160
                        and frame[(y * width + x) * 3 + 1] > 120
                        and frame[(y * width + x) * 3 + 2] < 150
                    ]
                    assert len(subject_points) > 100, (resolution, second, len(subject_points))
                    source_aspect, output_aspect = 1920 / 1080, width / height
                    crop_width = min(1, output_aspect / source_aspect) / zoom
                    crop_height = min(1, source_aspect / output_aspect) / zoom
                    left = (1 - crop_width) * camera_x / 100
                    top = (1 - crop_height) * camera_y / 100
                    expected_x = (subject_x / 1920 - left) / crop_width * width
                    expected_y = (subject_y / 1080 - top) / crop_height * height
                    actual_x = sum(x for x, _ in subject_points) / len(subject_points)
                    actual_y = sum(y for _, y in subject_points) / len(subject_points)
                    assert abs(actual_x - expected_x) < 35 and abs(actual_y - expected_y) < 45, (
                        resolution, second, (actual_x, actual_y), (expected_x, expected_y),
                    )

                title_frame, subtitle_frame = frame_at(1), frame_at(2.5)
                white_title = sum(
                    all(title_frame[(y * width + x) * 3 + channel] > 200 for channel in range(3))
                    for y in range(height // 20, height * 2 // 5) for x in range(width // 5, width * 4 // 5)
                )
                white_caption = sum(
                    all(subtitle_frame[(y * width + x) * 3 + channel] > 200 for channel in range(3))
                    for y in range(height * 2 // 3, height * 9 // 10) for x in range(width // 5, width * 4 // 5)
                )
                assert white_title > 20 and white_caption > 20, (resolution, white_title, white_caption)

                motion = subprocess.run([
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", "1.5", "-i", str(final),
                    "-vf", "fps=4,scale=180:320,format=rgb24", "-frames:v", "32", "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
                ], check=True, capture_output=True).stdout
                frame_size = 180 * 320 * 3
                assert len(motion) == frame_size * 32, (resolution, len(motion))
                centers, edge_means = [], []
                for index in range(32):
                    sampled = motion[index * frame_size:(index + 1) * frame_size]
                    yellow = [
                        (pixel // 3 % 180, pixel // 3 // 180)
                        for pixel in range(0, frame_size, 3)
                        if sampled[pixel] > 140 and sampled[pixel + 1] > 100
                        and sampled[pixel] > sampled[pixel + 1] and sampled[pixel + 1] > sampled[pixel + 2] * 1.1
                    ]
                    assert len(yellow) > 20, (resolution, index, len(yellow))
                    centers.append((sum(x for x, _ in yellow) / len(yellow), sum(y for _, y in yellow) / len(yellow)))
                    edge = [sampled[y * 180 * 3 + x * 3] + sampled[y * 180 * 3 + x * 3 + 1] + sampled[y * 180 * 3 + x * 3 + 2]
                            for x in range(0, 180, 4) for y in (0, 319)]
                    edge_means.append(sum(edge) / len(edge))
                scene_jumps = [
                    ((right[0] - left[0]) ** 2 + (right[1] - left[1]) ** 2) ** 0.5
                    for index, (left, right) in enumerate(zip(centers, centers[1:]))
                    if not any(start <= 1.5 + (index + 0.5) / 4 <= end for start, end in ((3.3, 4.0), (7.0, 7.7)))
                ]
                max_jump = max(scene_jumps)
                assert max_jump < 28 and max(edge_means) - min(edge_means) < 12, (resolution, max_jump, edge_means)

                if resolution == "1080":
                    CLIP_DIR.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(final.read_bytes())
                print(f"Dynamic Reframing {resolution} E2E passed: {width}x{height}")
            print(f"Synthetic E2E output: {output_path}")


if __name__ == "__main__":
    main()
