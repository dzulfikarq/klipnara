import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ["CLIPPER_DATA_DIR"] = tempfile.mkdtemp(prefix="klipnara-assets-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from clipper import asset_library, pexels
from clipper.config import SOURCE_DIR
from clipper.db import connect
from clipper.main import app
from clipper.media import MediaError


def _video(video_id="12345"):
    return {
        "id": video_id,
        "title": f"Pexels video {video_id}",
        "duration": 12,
        "width": 1920,
        "height": 1080,
        "orientation": "landscape",
        "page_url": f"https://www.pexels.com/video/{video_id}/",
        "preview_url": "https://images.pexels.com/videos/preview.jpg",
        "creator_name": "Fixture Creator",
        "creator_url": "https://www.pexels.com/@fixture/",
        "video_files": [{
            "id": 67890, "quality": "hd", "width": 1920, "height": 1080,
            "fps": 30, "link": "https://videos.pexels.com/video-files/12345/hd.mp4",
        }],
    }


def run():
    payload = {
        "id": 17,
        "url": "https://www.pexels.com/video/17/",
        "image": "https://images.pexels.com/videos/17/preview.jpeg",
        "duration": 8,
        "width": 1280,
        "height": 720,
        "user": {"name": "Fixture Creator", "url": "https://www.pexels.com/@fixture/"},
        "video_files": [
            {"id": 3, "file_type": "video/mp4", "quality": "hd", "width": 1280, "height": 720,
             "link": "https://videos.pexels.com/video-files/17/hd.mp4"},
            {"id": 4, "file_type": "video/mp4", "quality": "hd", "width": 1280, "height": 720,
             "link": "https://127.0.0.1/private.mp4"},
            {"id": 5, "file_type": "video/mp4", "quality": "hd", "width": 1280, "height": 720,
             "link": "https://videos.pexels.com.evil.example/video.mp4"},
        ],
    }
    parsed = pexels.parse_video(payload)
    assert parsed and parsed["id"] == "17" and len(parsed["video_files"]) == 1
    assert not pexels.parse_video({**payload, "id": "17"})
    with patch("clipper.pexels._api_json", return_value={"videos": [payload], "page": 1, "per_page": 30, "total_results": 1}) as api:
        pexels.search_videos("rain")
    assert api.call_args.args[0] == "/videos/search"
    assert "min_duration" not in api.call_args.args[1] and "max_duration" not in api.call_args.args[1]
    try:
        asset_library._safe_download_url("https://videos.pexels.com:444/video.mp4")
    except MediaError:
        pass
    else:
        raise AssertionError("nonstandard HTTPS port must be rejected")

    with patch("clipper.main.runner.start"):
        with TestClient(app) as client, patch.dict(os.environ, {"PEXELS_API_KEY": "fixture-only-key"}):
            with patch("clipper.asset_library.pexels.search_videos", return_value={"videos": [parsed, {**parsed, "id": "18", "duration": 40}], "page": 1, "per_page": 30, "total_results": 2}) as search:
                result = client.get("/api/assets/stock/search?query=rain&min_duration=5&max_duration=30")
            assert result.status_code == 200 and [video["id"] for video in result.json()["videos"]] == ["17"]
            assert search.call_args.args == ("rain", None, None, 1, 30)
            with patch("clipper.asset_library.pexels.search_videos", side_effect=pexels.PexelsError(429, "Pexels rate limit reached (429). Wait before retrying.")):
                limited = client.get("/api/assets/stock/search?query=rain")
            assert limited.status_code == 429

            with patch("clipper.asset_library.pexels.video_metadata", return_value=_video()):
                favorite = client.post("/api/assets/stock/favorites", json={"video_id": "12345"})
            assert favorite.status_code == 200 and favorite.json()["favorite"] is True
            assert len(client.get("/api/assets/stock/favorites").json()) == 1
            assert client.delete("/api/assets/stock/favorites/12345").status_code == 200

            with patch("clipper.asset_library._free_space", return_value=10**12), patch(
                "clipper.asset_library._probe_asset_file",
                return_value={"duration": 4.5, "width": None, "height": None, "video_codec": None, "audio_codec": "mp3"},
            ):
                uploaded = client.post(
                    "/api/assets/upload",
                    data={"kind": "audio", "title": "Quiet Piano"},
                    files={"file": ("quiet.mp3", b"mock audio", "audio/mpeg")},
                )
            assert uploaded.status_code == 200, uploaded.text
            asset = uploaded.json()
            assert asset["kind"] == "audio" and Path(asset["url"]).name == "file"
            with patch("clipper.asset_library._free_space", return_value=10**12), patch(
                "clipper.asset_library._probe_asset_file",
                return_value={"duration": 4.5, "width": None, "height": None, "video_codec": None, "audio_codec": "mp3"},
            ):
                duplicate = client.post(
                    "/api/assets/upload",
                    data={"kind": "audio", "title": "Duplicate"},
                    files={"file": ("other.mp3", b"mock audio", "audio/mpeg")},
                )
            assert duplicate.status_code == 200 and duplicate.json()["id"] == asset["id"]
            with connect() as conn:
                stored = conn.execute("SELECT path FROM library_assets WHERE id=?", (asset["id"],)).fetchone()
            shared_path = Path(stored["path"])
            assert shared_path.is_file()

            metadata = client.patch(f"/api/assets/{asset['id']}", json={
                "favorite": True, "artist": "Fixture Artist", "mood_tags": ["Calm", "Piano"],
                "license_type": "User recorded", "source_url": "https://example.com/license",
                "attribution_text": "Fixture attribution",
            })
            assert metadata.status_code == 200 and metadata.json()["favorite"] is True
            assert metadata.json()["mood_tags"] == ["Calm", "Piano"]
            assert client.patch(f"/api/assets/{asset['id']}", json={"source_url": "http://127.0.0.1/private"}).status_code == 422
            filtered = client.get("/api/assets?kind=audio&favorite=true&mood=Calm")
            assert filtered.status_code == 200 and filtered.json()["total"] == 1

            project = client.post("/api/mood-projects", json={}).json()["project"]
            attached = client.post(
                f"/api/mood-projects/{project['id']}/library-assets", json={"asset_id": asset["id"]}
            )
            assert attached.status_code == 200 and attached.json()["library_asset_id"] == asset["id"]
            assert Path(attached.json()["url"]).name == "file"
            assert client.delete(f"/api/assets/{asset['id']}").status_code == 409
            assert client.delete(f"/api/mood-projects/{project['id']}/assets/{attached.json()['id']}").status_code == 200
            assert shared_path.is_file(), "detaching Mood reference must preserve shared media"
            assert client.delete(f"/api/assets/{asset['id']}").status_code == 200
            assert not shared_path.exists()

            with patch("clipper.asset_library._submit_import"):
                created = client.post("/api/assets/stock/imports", json={
                    "video_id": "12345", "video_file_id": "67890", "quality": "hd",
                })
            assert created.status_code == 200 and created.json()["status"] == "queued"
            job_id = created.json()["id"]

            def fake_download(url, temporary, import_id, cancel_event):
                temporary.write_bytes(b"mock validated mp4")
                return temporary.stat().st_size

            with patch("clipper.asset_library.pexels.video_file", return_value=(_video(), _video()["video_files"][0])), patch(
                "clipper.asset_library._download_pexels", side_effect=fake_download,
            ), patch("clipper.asset_library.probe", return_value={
                "duration": 12.0, "width": 1920, "height": 1080, "video_codec": "h264", "audio_codec": "aac",
            }), patch("clipper.asset_library._free_space", return_value=10**12):
                asset_library._import_pexels(job_id)

            status = client.get(f"/api/assets/stock/imports/{job_id}")
            assert status.status_code == 200 and status.json()["status"] == "ready"
            imported = status.json()["asset"]
            assert imported["source"] == "pexels" and imported["creator_name"] == "Fixture Creator"
            with connect() as conn:
                source = conn.execute("SELECT id,path FROM sources WHERE id=?", (job_id,)).fetchone()
                count = conn.execute("SELECT count(*) FROM library_assets WHERE source='pexels' AND provider_asset_id='12345'").fetchone()[0]
                original_source_count = conn.execute("SELECT count(*) FROM sources").fetchone()[0]
            assert source and Path(source["path"]).is_file() and count == 1
            with patch("clipper.asset_library._submit_import"):
                reused = client.post("/api/assets/stock/imports", json={
                    "video_id": "12345", "video_file_id": "67890", "quality": "hd",
                })
            assert reused.status_code == 200 and reused.json()["reused"] is True

            with patch("clipper.asset_library._submit_import"):
                duplicate_file = client.post("/api/assets/stock/imports", json={
                    "video_id": "23456", "video_file_id": "67890", "quality": "hd",
                })
            duplicate_job = duplicate_file.json()["id"]
            with patch("clipper.asset_library.pexels.video_file", return_value=(_video("23456"), _video("23456")["video_files"][0])), patch(
                "clipper.asset_library._download_pexels", side_effect=fake_download,
            ), patch("clipper.asset_library.probe", return_value={
                "duration": 12.0, "width": 1920, "height": 1080, "video_codec": "h264", "audio_codec": "aac",
            }), patch("clipper.asset_library._free_space", return_value=10**12):
                asset_library._import_pexels(duplicate_job)
            deduped = client.get(f"/api/assets/stock/imports/{duplicate_job}").json()
            assert deduped["status"] == "ready" and deduped["asset"]["id"] == imported["id"]
            with connect() as conn:
                assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == original_source_count
            with patch("clipper.asset_library._submit_import"):
                duplicate_reuse = client.post("/api/assets/stock/imports", json={
                    "video_id": "23456", "video_file_id": "67890", "quality": "hd",
                })
            assert duplicate_reuse.status_code == 200 and duplicate_reuse.json()["reused"] is True

            with patch("clipper.asset_library._submit_import"):
                failed = client.post("/api/assets/stock/imports", json={
                    "video_id": "34567", "video_file_id": "67890", "quality": "hd",
                })
            failed_job = failed.json()["id"]
            protected = SOURCE_DIR / f"{failed_job}.mp4"
            protected.write_bytes(b"do not overwrite")
            def unique_download(url, temporary, import_id, cancel_event):
                temporary.write_bytes(b"unique mock video")
                return temporary.stat().st_size
            with patch("clipper.asset_library.pexels.video_file", return_value=(_video("34567"), _video("34567")["video_files"][0])), patch(
                "clipper.asset_library._download_pexels", side_effect=unique_download,
            ), patch("clipper.asset_library.probe", return_value={
                "duration": 12.0, "width": 1920, "height": 1080, "video_codec": "h264", "audio_codec": "aac",
            }), patch("clipper.asset_library._free_space", return_value=10**12):
                asset_library._import_pexels(failed_job)
            assert client.get(f"/api/assets/stock/imports/{failed_job}").json()["status"] == "failed"
            assert protected.read_bytes() == b"do not overwrite"
            protected.unlink()
            with patch("clipper.asset_library._submit_import"):
                retried = client.post(f"/api/assets/stock/imports/{failed_job}/retry")
            assert retried.status_code == 200 and retried.json()["status"] == "queued"
            assert client.post(f"/api/assets/stock/imports/{failed_job}/cancel").status_code == 200
            asset_library._import_pexels(failed_job)
            assert client.get(f"/api/assets/stock/imports/{failed_job}").json()["status"] == "cancelled"

            project = client.post("/api/mood-projects", json={}).json()["project"]
            linked = client.post(f"/api/mood-projects/{project['id']}/library-assets", json={"asset_id": imported["id"]})
            assert linked.status_code == 200 and linked.json()["source_id"] == job_id
            assert linked.json()["creator_name"] == "Fixture Creator" and linked.json()["source_url"].startswith("https://www.pexels.com/")
            assert client.delete(f"/api/assets/{imported['id']}").status_code == 409
            assert client.delete(f"/api/sources/{job_id}").status_code == 409
            assert client.delete(f"/api/mood-projects/{project['id']}/assets/{linked.json()['id']}").status_code == 200
            assert Path(source["path"]).is_file(), "detaching imported footage must preserve Quick Clip source"
            assert client.get("/api/sources").status_code == 200

    print("Asset Library mocked API/import checks passed")


if __name__ == "__main__":
    run()
