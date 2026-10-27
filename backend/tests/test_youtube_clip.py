import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

os.environ["CLIPPER_DATA_DIR"] = tempfile.mkdtemp(prefix="klipnara-youtube-clip-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from clipper.config import SOURCE_DIR
from clipper.db import connect
from clipper.main import app
from clipper.youtube_clip import fetch_youtube_metadata, parse_youtube_url


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size=-1):
        return self.body if size < 0 else self.body[:size]


def run():
    video_id = "Zz7os_kWwnM"
    expected_url = f"https://www.youtube.com/watch?v={video_id}"
    example_urls = (
        f"https://youtu.be/{video_id}?si=K1t7XMIZuDy10liL",
        expected_url,
    )
    assert [parse_youtube_url(value)["video_id"] for value in example_urls] == [video_id, video_id]
    formats = (
        f"https://youtube.com/watch?v={video_id}&si=tracking&t=1m2s&feature=share",
        f"https://www.youtube.com/watch?v={video_id}&start=90",
        f"https://m.youtube.com/watch?v={video_id}&t=01:02",
        f"https://youtu.be/{video_id}?t=3723",
        f"https://youtube.com/shorts/{video_id}?start=1h2m3s",
    )
    for value in formats:
        result = parse_youtube_url(value)
        assert result["video_id"] == video_id and result["canonical_url"] == expected_url
    assert parse_youtube_url(formats[0])["start_seconds"] == 62
    assert parse_youtube_url(formats[1])["start_seconds"] == 90
    assert parse_youtube_url(formats[2])["start_seconds"] == 62
    assert parse_youtube_url(formats[3])["start_seconds"] == 3723
    assert parse_youtube_url(formats[4])["start_seconds"] == 3723
    assert parse_youtube_url(f"https://youtu.be/{video_id}?t=invalid")["start_seconds"] is None
    assert parse_youtube_url(f"https://youtu.be/{video_id}?t=1m60s")["start_seconds"] is None
    assert parse_youtube_url(f"https://youtu.be/{video_id}?t=1h60m")["start_seconds"] is None
    assert parse_youtube_url(f"https://youtu.be/{video_id}?t=9" + "0" * 20)["start_seconds"] is None

    invalid_urls = (
        "https://youtube.com.evil.example/watch?v=" + video_id,
        "https://youtu.be.evil.example/" + video_id,
        "https://youtube.com@evil.example/watch?v=" + video_id,
        "https://evil.example/youtube.com/watch?v=" + video_id,
        "file:///youtube.com/watch?v=" + video_id,
        "https://youtube.com:8443/watch?v=" + video_id,
        "https://youtube.com/watch?v=short",
        "https://youtube.com/embed/" + video_id,
        "https://youtube.com/watch?v=" + video_id + "&v=" + video_id,
    )
    for value in invalid_urls:
        try:
            parse_youtube_url(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Accepted invalid YouTube URL: {value}")

    with patch.dict(os.environ, {"YOUTUBE_DATA_API_KEY": ""}), patch("clipper.youtube_clip.urllib.request.urlopen") as open_url:
        missing_key = fetch_youtube_metadata(video_id)
    assert missing_key["metadata_status"] == "not_configured" and missing_key["metadata"] is None
    open_url.assert_not_called()

    payload = {"items": [{
        "snippet": {
            "title": "Test title", "channelTitle": "Test channel",
            "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"}},
        },
        "contentDetails": {"duration": "PT1H2M3S"},
        "status": {"embeddable": True},
    }]}
    with patch.dict(os.environ, {"YOUTUBE_DATA_API_KEY": "server-only-test-key"}), patch(
        "clipper.youtube_clip.urllib.request.urlopen", return_value=FakeResponse(payload),
    ) as open_url:
        metadata = fetch_youtube_metadata(video_id)
    request_url = open_url.call_args.args[0].full_url
    assert request_url.startswith("https://www.googleapis.com/youtube/v3/videos?")
    assert "server-only-test-key" in request_url and metadata["metadata_status"] == "available"
    assert metadata["metadata"] == {
        "title": "Test title", "channel": "Test channel",
        "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "duration_seconds": 3723, "embeddable": True,
    }

    with patch.dict(os.environ, {"YOUTUBE_DATA_API_KEY": "test-key"}), patch(
        "clipper.youtube_clip.urllib.request.urlopen", return_value=FakeResponse({"items": []}),
    ):
        assert fetch_youtube_metadata(video_id)["metadata_status"] == "unavailable"
    with patch.dict(os.environ, {"YOUTUBE_DATA_API_KEY": "test-key"}), patch(
        "clipper.youtube_clip.urllib.request.urlopen", return_value=FakeResponse({"items": [{
            "snippet": {"title": "No embed", "channelTitle": "Test"},
            "contentDetails": {"duration": "PT30S"}, "status": {"embeddable": False},
        }]}),
    ):
        assert fetch_youtube_metadata(video_id)["metadata"]["embeddable"] is False
    quota = HTTPError(
        "https://www.googleapis.com/youtube/v3/videos", 403, "quota", {},
        io.BytesIO(json.dumps({"error": {"errors": [{"reason": "quotaExceeded"}]}}).encode()),
    )
    with patch.dict(os.environ, {"YOUTUBE_DATA_API_KEY": "test-key"}), patch(
        "clipper.youtube_clip.urllib.request.urlopen", side_effect=quota,
    ):
        assert fetch_youtube_metadata(video_id)["metadata_status"] == "quota_exceeded"
    unavailable = HTTPError(
        "https://www.googleapis.com/youtube/v3/videos", 404, "not found", {},
        io.BytesIO(json.dumps({"error": {"errors": [{"reason": "videoNotFound"}]}}).encode()),
    )
    with patch.dict(os.environ, {"YOUTUBE_DATA_API_KEY": "test-key"}), patch(
        "clipper.youtube_clip.urllib.request.urlopen", side_effect=unavailable,
    ):
        assert fetch_youtube_metadata(video_id)["metadata_status"] == "unavailable"
    with patch.dict(os.environ, {"YOUTUBE_DATA_API_KEY": "test-key"}), patch(
        "clipper.youtube_clip.urllib.request.urlopen", side_effect=URLError("offline"),
    ):
        assert fetch_youtube_metadata(video_id)["metadata_status"] == "network_error"

    with patch("clipper.main.runner.start"):
        with TestClient(app) as client:
            metadata_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/youtube-clips/metadata")
            assert metadata_route.methods == {"POST"}
            assert client.get("/api/youtube-clips/metadata").status_code == 405
            assert client.post("/api/youtube-clips/metadatas", json={"url": expected_url}).status_code == 404
            assert client.get("/api/mood-quotes/categories").status_code == 200
            assert client.post("/api/mood-projects", json={}).status_code == 200
            with patch.dict(os.environ, {"YOUTUBE_DATA_API_KEY": ""}), patch(
                "clipper.youtube_clip.urllib.request.urlopen", side_effect=AssertionError("metadata called arbitrary media URL"),
            ), patch("clipper.media.download_url", side_effect=AssertionError("YouTube URL triggered media download")), patch(
                "clipper.main.download_url", side_effect=AssertionError("YouTube URL reached direct-file importer"),
            ):
                valid = client.post("/api/youtube-clips/metadata", json={"url": formats[0]})
                valid_example = client.post("/api/youtube-clips/metadata", json={"url": example_urls[0]})
                valid_watch = client.post("/api/youtube-clips/metadata", json={"url": example_urls[1]})
                invalid = client.post("/api/youtube-clips/metadata", json={"url": invalid_urls[0]})
            assert valid.status_code == 200 and valid.json()["video_id"] == video_id
            assert valid_example.status_code == valid_watch.status_code == 200
            assert valid_example.json()["video_id"] == valid_watch.json()["video_id"] == video_id
            assert invalid.status_code == 422
            with patch("clipper.main.fetch_youtube_metadata", side_effect=RuntimeError("metadata provider unavailable")):
                metadata_failure = client.post("/api/youtube-clips/metadata", json={"url": example_urls[0]})
            assert metadata_failure.status_code == 200
            assert metadata_failure.json()["metadata"] is None and metadata_failure.json()["metadata_status"] == "api_error"
            with patch("clipper.main.fetch_youtube_metadata", return_value={
                "metadata": None, "metadata_status": "unavailable", "metadata_message": "video not verified",
            }):
                provider_not_found = client.post("/api/youtube-clips/metadata", json={"url": example_urls[0]})
            assert provider_not_found.status_code == 200
            assert provider_not_found.json()["metadata_status"] == "unavailable"
            with patch("clipper.media._public_addresses", side_effect=AssertionError("YouTube URL triggered DNS lookup")):
                blocked_import = client.post("/api/sources/url", json={"url": formats[0]})
            assert blocked_import.status_code == 400 and "preview references" in blocked_import.json()["detail"]

            with patch("clipper.main.probe", return_value={"duration": 120, "width": 1280, "height": 720, "video_codec": "h264", "audio_codec": "aac"}):
                uploaded = client.post("/api/sources/upload", files={"file": ("Test title.mp4", io.BytesIO(b"selected-local-source"), "video/mp4")})
            assert uploaded.status_code == 200, uploaded.text
            source = uploaded.json()
            source_id = source["id"]
            source_path = SOURCE_DIR / f"{source_id}.mp4"
            assert source["name"] == "Test title.mp4"
            assert any(item["id"] == source_id for item in client.get("/api/sources").json())
            smart = client.post(f"/api/sources/{source_id}/generate", json={"provider": "local"})
            assert smart.status_code == 200
            with connect() as conn:
                assert conn.execute("SELECT kind FROM jobs WHERE id=?", (smart.json()["id"],)).fetchone()[0] == "generate"

            body = {
                "title": "Linked by user", "start": 12, "end": 37, "resolution": "1080",
                "youtube_reference": {"canonical_url": expected_url, "video_id": video_id},
            }
            with patch("clipper.main.probe", return_value={"duration": 20, "width": 1280, "height": 720, "video_codec": "h264", "audio_codec": "aac"}), patch(
                "clipper.media.download_url", side_effect=AssertionError("Quick Clip downloaded YouTube media"),
            ), patch("clipper.main.download_url", side_effect=AssertionError("Quick Clip reached direct-file importer")):
                too_long = client.post(f"/api/sources/{source_id}/quick-clips", json=body)
            assert too_long.status_code == 422 and "current local source duration" in too_long.json()["detail"]

            with patch("clipper.main.probe", return_value={"duration": 45, "width": 1280, "height": 720, "video_codec": "h264", "audio_codec": "aac"}), patch(
                "clipper.media.download_url", side_effect=AssertionError("Quick Clip downloaded YouTube media"),
            ), patch("clipper.main.download_url", side_effect=AssertionError("Quick Clip reached direct-file importer")):
                created = client.post(f"/api/sources/{source_id}/quick-clips", json=body)
            assert created.status_code == 200, created.text
            clip_id = created.json()["clip_id"]
            with connect() as conn:
                clip = conn.execute("SELECT source_id,start,end,edit_json,job_id FROM clips WHERE id=?", (clip_id,)).fetchone()
                options = json.loads(conn.execute("SELECT options_json FROM jobs WHERE id=?", (clip["job_id"],)).fetchone()[0])
            assert clip["source_id"] == source_id and (clip["start"], clip["end"]) == (12, 37)
            assert json.loads(clip["edit_json"])["resolution"] == "1080"
            assert options["youtube_reference"] == {
                "canonical_url": expected_url, "video_id": video_id,
                "start": 12, "end": 37, "source_association": "user_selected",
            }
            detail = client.get(f"/api/clips/{clip_id}").json()
            assert detail["clip"]["source_id"] == source_id
            assert detail["clip"]["youtube_reference"]["video_id"] == video_id
            assert detail["clip"]["youtube_reference"]["source_association"] == "user_selected"
            assert detail["source"]["name"] == "Test title.mp4"
            assert source_path.read_bytes() == b"selected-local-source"
            assert client.delete(f"/api/clips/{clip_id}/youtube-reference").json() == {"deleted": True}
            assert client.get(f"/api/clips/{clip_id}").json()["clip"]["youtube_reference"] is None
            assert client.delete(f"/api/clips/{clip_id}/youtube-reference").json() == {"deleted": False}
            source_path.unlink(missing_ok=True)

    print("YouTube Clip URL, metadata fallback, local source linkage, timestamp forwarding, and no-download checks added")


if __name__ == "__main__":
    run()
