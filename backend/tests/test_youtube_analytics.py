import json
import os
import sys
import tempfile
import uuid
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ["CLIPPER_DATA_DIR"] = tempfile.mkdtemp(prefix="klipnara-analytics-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from clipper.db import connect, init_db
from clipper.jobs import now, runner
from clipper.main import app
from clipper import youtube, youtube_analytics


def _seed_account_and_publication():
    account_id, channel_id = uuid.uuid4().hex, "UC" + uuid.uuid4().hex[:20]
    publication_id, video_id = uuid.uuid4().hex, "video" + uuid.uuid4().hex[:7]
    timestamp = now()
    scopes = sorted(youtube.ANALYTICS_SCOPES + (youtube.UPLOAD_SCOPE,))
    with connect() as conn:
        conn.execute(
            "INSERT INTO youtube_accounts(id,channel_id,channel_title,status,token_blob,expires_at,channel_avatar_url,"
            "verified_at,granted_scopes_json,created_at,updated_at) VALUES(?,?,?,'connected',?,?,NULL,?,?,?,?)",
            (account_id, channel_id, "Analytics Fixture", youtube.encrypt_secret(json.dumps({
                "access_token": "mock-access", "refresh_token": "mock-refresh",
            })), 4102444800, timestamp, json.dumps(scopes), timestamp, timestamp),
        )
        conn.execute(
            "INSERT INTO youtube_publications(id,account_id,clip_id,clip_title,status,title,description,tags_json,"
            "privacy_status,made_for_kids,contains_synthetic_media,content_type,category_id,hashtags_json,"
            "rendered_path,rendered_sha256,file_size,duration,width,height,video_id,video_url,published_at,"
            "attribution_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (publication_id, account_id, uuid.uuid4().hex, "Fixture clip", "published", "Published fixture", "",
             "[]", "public", 0, 0, "clip", "22", "[]", "local-only.mp4", "fixture-hash", 123, 40, 720, 1280,
             video_id, f"https://youtu.be/{video_id}", timestamp,
             json.dumps({"source_workflow": "quick_clip", "subtitle_type": "Word Pop", "number_of_scenes": 2}),
             timestamp, timestamp),
        )
    return account_id, channel_id, publication_id, video_id


def _seed_second_publication(account_id):
    publication_id, video_id = uuid.uuid4().hex, "video" + uuid.uuid4().hex[:7]
    timestamp = now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO youtube_publications(id,account_id,clip_id,clip_title,status,title,description,tags_json,"
            "privacy_status,made_for_kids,contains_synthetic_media,content_type,category_id,hashtags_json,"
            "rendered_path,rendered_sha256,file_size,duration,width,height,video_id,video_url,published_at,"
            "attribution_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (publication_id, account_id, uuid.uuid4().hex, "Second fixture", "published", "Second published fixture", "",
             "[]", "public", 0, 0, "clip", "22", "[]", "local-only-2.mp4", "fixture-hash-2", 123, 40, 720, 1280,
             video_id, f"https://youtu.be/{video_id}", timestamp,
             json.dumps({"source_workflow": "quick_clip", "subtitle_type": "Standard"}), timestamp, timestamp),
        )
    return video_id


def _report(params):
    dimensions = params["dimensions"].split(",")
    metrics = params["metrics"].split(",")
    names = dimensions + metrics
    headers = [{"name": name} for name in names]
    if "elapsedVideoTimeRatio" in dimensions:
        rows = [[0.0, 0.82, 0.0], [0.5, 0.43, 0.1], [1.0, 0.12, -0.2]]
    else:
        metric_values = {
            "views": 11, "engagedViews": 5, "estimatedMinutesWatched": 8,
            "averageViewDuration": 22, "averageViewPercentage": 61,
            "subscribersGained": 2, "subscribersLost": 1,
            "likes": 3, "comments": 1, "shares": 1,
        }
        values = [metric_values.get(name, 0) for name in metrics]
        if "day" in dimensions:
            first = date.fromisoformat(params["startDate"])
            rows = [[first.isoformat(), *values], [(first + timedelta(days=1)).isoformat(), *values]]
        elif "video" in dimensions:
            filter_value = params.get("filters", "video==fixture").removeprefix("video==").split(",")[0]
            rows = [[filter_value, *values]]
        else:
            rows = []
    return {"columnHeaders": headers, "rows": rows}


def run():
    init_db()
    account_id, _channel_id, publication_id, video_id = _seed_account_and_publication()
    second_video_id = _seed_second_publication(account_id)
    start = (date.today() - timedelta(days=4)).isoformat()
    end = (date.today() - timedelta(days=2)).isoformat()
    calls = []

    def fake_report(_account_id, method, url, **_kwargs):
        from urllib.parse import parse_qs, urlsplit
        assert method == "GET"
        params = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        calls.append(params)
        return _report(params)

    with patch("clipper.main.runner.start"), TestClient(app) as client, patch(
        "clipper.youtube._authorized_json", side_effect=fake_report,
    ):
        channel = youtube_analytics.dashboard(account_id, "channel", start, end)
        assert channel["metrics"]["views"] == 22
        assert channel["metrics"]["engaged_views"] == 10
        assert channel["metrics"]["views"] != channel["metrics"]["engaged_views"]
        assert channel["channel_video_limit_reached"] is False
        assert channel["comparison"]["metrics"]["views"] == 22
        first_call_count = len(calls)
        cached = youtube_analytics.dashboard(account_id, "channel", start, end)
        assert cached["cached"] is True and len(calls) == first_call_count
        channel_daily_params = {
            "startDate": start, "endDate": end, "metrics": youtube_analytics.CHANNEL_METRICS,
            "dimensions": "day", "sort": "day", "maxResults": 200,
        }
        account = youtube_analytics._account(account_id)
        with patch("clipper.youtube._authorized_json", side_effect=youtube.YouTubeError(
            "mock report failure", status=400,
        )):
            try:
                youtube_analytics._query(account, channel_daily_params, force=True)
            except youtube_analytics.AnalyticsError as error:
                assert error.code == "analytics_query_invalid"
            else:
                raise AssertionError("Forced report failure must be returned")
        stale_report, _fetched_at, from_cache = youtube_analytics._query(account, channel_daily_params)
        assert from_cache and stale_report["rows"][0]["views"] == 11

        attributed = youtube_analytics.dashboard(account_id, "klipnara", start, end)
        assert attributed["metrics"]["views"] == 44
        assert attributed["metrics"]["subscribers_gained"] is None
        assert {row["video_id"] for row in attributed["videos"]} == {video_id, second_video_id}
        assert next(row for row in attributed["videos"] if row["video_id"] == video_id)["attribution"]["subtitle_type"] == "Word Pop"
        attributed_filters = {call["filters"] for call in calls if call.get("filters", "").startswith("video==")}
        assert {f"video=={video_id}", f"video=={second_video_id}"}.issubset(attributed_filters)
        assert all("," not in value for value in attributed_filters)

        long_range_params = {
            "startDate": "2025-01-01", "endDate": "2025-12-31", "metrics": youtube_analytics.CHANNEL_METRICS,
            "dimensions": "day", "sort": "day",
        }
        before_long_range = len(calls)
        youtube_analytics._query_day_range(account, long_range_params)
        long_range_calls = calls[before_long_range:]
        assert len(long_range_calls) == 2
        assert all(int(call["maxResults"]) <= 200 for call in long_range_calls)
        assert sum((date.fromisoformat(call["endDate"]) - date.fromisoformat(call["startDate"])).days + 1 for call in long_range_calls) == 365

        detail = youtube_analytics.video_detail(publication_id, start, end)
        assert detail["metrics"]["views"] == 22 and detail["video_id"] == video_id
        retention = youtube_analytics.retention(publication_id, start, end)
        assert len(retention["points"]) == 3
        assert retention["points"][1]["timestamp_seconds"] == 20

        response = client.get("/api/youtube/analytics", params={
            "account_id": account_id, "scope": "channel", "start_date": start, "end_date": end,
        })
        assert response.status_code == 200 and response.json()["metrics"]["engaged_views"] == 10
        invalid_scope = client.get("/api/youtube/analytics", params={"account_id": account_id, "scope": "all_channels"})
        assert invalid_scope.status_code == 422
        assert invalid_scope.json()["detail"]["code"] == "analytics_scope_invalid"

        with connect() as conn:
            conn.execute("UPDATE youtube_accounts SET granted_scopes_json='[]' WHERE id=?", (account_id,))
        denied = client.get("/api/youtube/analytics", params={"account_id": account_id})
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "analytics_scope_required"

    try:
        youtube_analytics.parse_report({"columnHeaders": [{"name": "views"}], "rows": [[1, 2]]})
    except youtube_analytics.AnalyticsError as exc:
        assert exc.code == "analytics_response_invalid"
    else:
        raise AssertionError("Malformed Analytics rows must fail closed")
    try:
        youtube_analytics.date_range("2026-02-30", "2026-03-01")
    except youtube_analytics.AnalyticsError as exc:
        assert exc.code == "analytics_date_invalid"
    else:
        raise AssertionError("Invalid Analytics date must be rejected")
    try:
        youtube_analytics.date_range("20260301", "2026-03-02")
    except youtube_analytics.AnalyticsError as exc:
        assert exc.code == "analytics_date_invalid"
    else:
        raise AssertionError("Non-canonical Analytics dates must be rejected")
    assert youtube_analytics._provider_error(youtube.YouTubeError(
        "rate limited", status=403, reason="userRateLimitExceeded",
    )).code == "analytics_rate_limited"
    assert youtube_analytics._summary([], include_subscribers=False)["views"] is None
    weighted = youtube_analytics._combine_rows([
        {"views": 1, "averageViewDuration": 10, "averageViewPercentage": 20},
        {"views": 3, "averageViewDuration": 50, "averageViewPercentage": 60},
    ], "day", "2026-01-01")
    assert weighted["averageViewDuration"] == 40 and weighted["averageViewPercentage"] == 50
    insight_videos = [
        {"attribution": {"base_workflow": "quick_clip", "subtitle_type": "Word Pop"}, "engagedViews": 10, "averageViewPercentage": 60}
        for _ in range(5)
    ] + [
        {"attribution": {"base_workflow": "ai_smart_clip", "subtitle_type": "Standard"}, "engagedViews": 5, "averageViewPercentage": 40}
        for _ in range(5)
    ]
    insights = youtube_analytics.build_insights(insight_videos, start, end)
    assert len(insights["items"]) == 3
    assert all("n=5" in item["message"] for item in insights["items"] if item["kind"] == "comparison")
    assert youtube_analytics.build_insights(insight_videos[:4], start, end)["items"] == []

    page_calls = []
    def paged_report(_account_id, method, url, **_kwargs):
        from urllib.parse import parse_qs, urlsplit
        params = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        page_calls.append(params)
        dimensions, metrics = params["dimensions"].split(","), params["metrics"].split(",")
        count = 200 if params["startIndex"] == "1" else 50
        values = {"views": 1, "engagedViews": 1, "estimatedMinutesWatched": 1,
                  "averageViewDuration": 1, "averageViewPercentage": 1, "likes": 1, "comments": 1, "shares": 1}
        return {"columnHeaders": [{"name": name} for name in dimensions + metrics],
                "rows": [[f"page-video-{params['startIndex']}-{index}", *[values[name] for name in metrics]] for index in range(count)]}

    with patch("clipper.youtube._authorized_json", side_effect=paged_report):
        paged, _fetched_at, _cached, capped = youtube_analytics._query_paginated(
            account, {"startDate": start, "endDate": end, "metrics": youtube_analytics.VIDEO_METRICS,
                      "dimensions": "video", "sort": "-views"}, force=True,
        )
    assert len(paged["rows"]) == 250 and not capped
    assert [call["startIndex"] for call in page_calls] == ["1", "201"]
    assert [call["maxResults"] for call in page_calls] == ["200", "200"]
    print("YouTube Analytics parsing, per-video attribution, bounded pagination, cache, comparisons, retention, and scope checks passed")


if __name__ == "__main__":
    run()
