import os
import sys
import tempfile
import uuid
from pathlib import Path

os.environ["CLIPPER_DATA_DIR"] = tempfile.mkdtemp(prefix="clipper-test-")
os.environ["OPENAI_API_KEY"] = "test-only-key"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from clipper.db import connect
from clipper.jobs import now
from clipper.main import app


def run():
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        capabilities = client.get("/api/system/capabilities").json()
        assert capabilities["cpu"] and capabilities["ram_bytes"] and capabilities["gpus"]
        assert client.post("/api/sources/url", json={"url": "http://127.0.0.1/video.mp4"}).status_code == 400
        assert client.post("/api/sources/url", json={"url": "https://127.0.0.1/video.mp4"}).status_code == 400

        source_id = uuid.uuid4().hex
        with connect() as conn:
            conn.execute(
                "INSERT INTO sources(id,name,path,size_bytes,duration,width,height,video_codec,sha256,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (source_id, "test.mp4", "unavailable.mp4", 1, 120, 1280, 720, "h264", "test", now()),
            )
        endpoint = f"/api/sources/{source_id}/generate"
        cloud = {"provider": "openai", "consent": False}
        assert client.post(endpoint, json=cloud).status_code == 400
        cloud["consent"] = True
        result = client.post(endpoint, json=cloud)
        assert result.status_code == 200
        with connect() as conn:
            row = conn.execute("SELECT options_json FROM jobs WHERE id=?", (result.json()["id"],)).fetchone()
        assert '"consent_at":' in row["options_json"]
    print("API privacy, consent, and route checks passed")


if __name__ == "__main__":
    run()
