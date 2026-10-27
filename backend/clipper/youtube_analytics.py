import hashlib
import json
import math
import statistics
import threading
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from .db import connect
from .jobs import now
from . import youtube


REPORT_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
CACHE_TTL_SECONDS = 6 * 60 * 60
CACHE_RETENTION_SECONDS = 30 * 24 * 60 * 60
MIN_INSIGHT_SAMPLE = 5
REPORT_PAGE_SIZE = 200
VIDEO_REPORT_LIMIT = 500
CHANNEL_METRICS = (
    "views,engagedViews,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
    "subscribersGained,subscribersLost,likes,comments,shares"
)
PRODUCTION_METRICS = "views,engagedViews,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,shares"
VIDEO_METRICS = PRODUCTION_METRICS
TREND_METRICS = "views,engagedViews,estimatedMinutesWatched"
RETENTION_METRICS = "audienceWatchRatio,relativeRetentionPerformance"
_SYNC_LOCK = threading.Lock()


def clear_channel_cache(channel_id):
    with _SYNC_LOCK:
        with connect() as conn:
            conn.execute("DELETE FROM youtube_analytics_cache WHERE channel_id=?", (channel_id,))


class AnalyticsError(RuntimeError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def _provider_error(error, *, data_api=False):
    reason = getattr(error, "reason", None)
    status = getattr(error, "status", None)
    if reason == "accessNotConfigured":
        if data_api:
            return AnalyticsError("youtube_data_api_disabled", "Aktifkan YouTube Data API v3 untuk memverifikasi channel.", 503)
        return AnalyticsError("analytics_api_disabled", "Aktifkan YouTube Analytics API pada Google Cloud project Klipnara.", 503)
    if reason in {"quotaExceeded", "dailyLimitExceeded"}:
        return AnalyticsError("analytics_quota_exceeded", "Kuota YouTube Analytics API habis. Coba lagi setelah kuota pulih.", 429)
    if status == 429 or reason in {"rateLimitExceeded", "userRateLimitExceeded"}:
        return AnalyticsError("analytics_rate_limited", "YouTube membatasi permintaan sementara. Tunggu sebelum refresh lagi.", 429)
    if status == 401 or reason == "invalid_grant":
        return AnalyticsError("oauth_reauthorization_required", "Izin YouTube kedaluwarsa atau dicabut. Hubungkan ulang channel.", 401)
    if reason in {"insufficientPermissions", "insufficient_scope"} or status == 403:
        return AnalyticsError("analytics_permission_required", "Google menolak akses Analytics. Periksa izin channel dan scope OAuth.", 403)
    if status == 400:
        return AnalyticsError("analytics_query_invalid", "YouTube menolak kombinasi metrik atau rentang laporan ini.", 422)
    if status == 404:
        return AnalyticsError("analytics_video_unavailable", "Video tidak tersedia untuk channel yang terhubung.", 404)
    if getattr(error, "retryable", False):
        return AnalyticsError("analytics_temporarily_unavailable", "YouTube Analytics sedang tidak tersedia. Coba refresh nanti.", 503)
    return AnalyticsError("analytics_api_failed", "Permintaan YouTube Analytics gagal. Periksa koneksi dan konfigurasi API.", 502)


def _account(account_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT id,channel_id,channel_title,status,token_blob,verified_at,granted_scopes_json "
            "FROM youtube_accounts WHERE id=?", (account_id,),
        ).fetchone()
    if not row or row["status"] == "disconnected" or not row["token_blob"]:
        raise AnalyticsError("youtube_not_connected", "Hubungkan channel YouTube dari Connected Accounts terlebih dahulu.", 409)
    if row["status"] != "connected":
        raise AnalyticsError("oauth_reauthorization_required", "Izin YouTube kedaluwarsa atau bermasalah. Hubungkan ulang channel.", 401)
    scopes = set(json.loads(row["granted_scopes_json"])) if row["granted_scopes_json"] else set()
    required = set(youtube.ANALYTICS_SCOPES)
    if not required.issubset(scopes):
        raise AnalyticsError("analytics_scope_required", "Izin Analytics diperlukan. Klik Aktifkan Analytics pada Connected Accounts.", 403)
    if not row["verified_at"]:
        try:
            youtube.verify_account(account_id)
        except youtube.YouTubeError as error:
            raise _provider_error(error, data_api=True) from None
    return dict(row)


def date_range(start_date=None, end_date=None):
    last_complete_candidate = datetime.now(timezone.utc).date() - timedelta(days=1)
    try:
        end = date.fromisoformat(end_date) if end_date else last_complete_candidate
        start = date.fromisoformat(start_date) if start_date else end - timedelta(days=27)
    except (TypeError, ValueError):
        raise AnalyticsError("analytics_date_invalid", "Tanggal harus memakai format YYYY-MM-DD.", 422) from None
    if (start_date is not None and start.isoformat() != start_date) or (end_date is not None and end.isoformat() != end_date):
        raise AnalyticsError("analytics_date_invalid", "Tanggal harus memakai format YYYY-MM-DD.", 422)
    if start > end or end > last_complete_candidate or (end - start).days > 365:
        raise AnalyticsError("analytics_date_invalid", "Rentang tanggal harus valid, tidak mencakup hari berjalan, dan maksimal 366 hari.", 422)
    return start.isoformat(), end.isoformat()


def parse_report(payload, requested_start=None, requested_end=None, expected_columns=None):
    if not isinstance(payload, dict):
        raise AnalyticsError("analytics_response_invalid", "YouTube mengembalikan laporan dengan format tidak valid.", 502)
    headers = payload.get("columnHeaders") or []
    rows = payload.get("rows") or []
    if not isinstance(headers, list) or not isinstance(rows, list):
        raise AnalyticsError("analytics_response_invalid", "YouTube mengembalikan tabel laporan yang tidak valid.", 502)
    names = [header.get("name") if isinstance(header, dict) else None for header in headers]
    if any(not isinstance(name, str) or not name for name in names) or len(names) != len(set(names)):
        raise AnalyticsError("analytics_response_invalid", "Kolom laporan YouTube tidak dapat dipetakan.", 502)
    if expected_columns is not None and names != expected_columns:
        raise AnalyticsError("analytics_response_invalid", "Kolom laporan YouTube tidak cocok dengan metrik yang diminta.", 502)
    output = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(names):
            raise AnalyticsError("analytics_response_invalid", "Jumlah kolom baris laporan tidak sesuai header.", 502)
        item = dict(zip(names, row))
        for name in names:
            if name in {"day", "video", "elapsedVideoTimeRatio"}:
                continue
            value = item[name]
            if value is None or value == "":
                item[name] = None
                continue
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError):
                raise AnalyticsError("analytics_response_invalid", "Metrik laporan YouTube bukan angka yang valid.", 502) from None
            if not math.isfinite(number):
                raise AnalyticsError("analytics_response_invalid", "Metrik laporan YouTube bukan angka finite.", 502)
            item[name] = number
        if "day" in item:
            try:
                day = date.fromisoformat(item["day"])
                if day.isoformat() != item["day"]:
                    raise ValueError
                item["day"] = day.isoformat()
            except (TypeError, ValueError):
                raise AnalyticsError("analytics_response_invalid", "Tanggal laporan YouTube tidak valid.", 502) from None
        if "elapsedVideoTimeRatio" in item:
            try:
                ratio = float(item["elapsedVideoTimeRatio"])
            except (TypeError, ValueError, OverflowError):
                raise AnalyticsError("analytics_response_invalid", "Posisi retensi YouTube tidak valid.", 502) from None
            if not math.isfinite(ratio) or not 0 <= ratio <= 1:
                raise AnalyticsError("analytics_response_invalid", "Posisi retensi YouTube di luar rentang 0–1.", 502)
            item["elapsedVideoTimeRatio"] = ratio
        output.append(item)
    days = [row["day"] for row in output if isinstance(row.get("day"), str)]
    return {
        "rows": output,
        "coverage": {"start_date": min(days) if days else None, "end_date": max(days) if days else None},
        "requested": {"start_date": requested_start, "end_date": requested_end},
        "columns": names,
    }


def _query(account, params, *, force=False):
    full_params = {"ids": f"channel=={account['channel_id']}", **params}
    query_json = json.dumps(full_params, sort_keys=True, separators=(",", ":"))
    query_key = hashlib.sha256(query_json.encode()).hexdigest()
    current = time.time()
    # ponytail: one sync at a time per backend process; per-channel locks if multi-channel throughput matters.
    with _SYNC_LOCK:
        with connect() as conn:
            conn.execute(
                "DELETE FROM youtube_analytics_cache WHERE fetched_at<? OR attempted_at<?",
                (current - CACHE_RETENTION_SECONDS, current - CACHE_RETENTION_SECONDS),
            )
            cached = conn.execute(
                "SELECT * FROM youtube_analytics_cache WHERE channel_id=? AND query_key=?",
                (account["channel_id"], query_key),
            ).fetchone()
        if cached and cached["status"] == "failed" and current - cached["attempted_at"] < 30 and not force:
            raise AnalyticsError(cached["error_code"], cached["error_message"], 503)
        if (
            cached and cached["status"] == "ok" and cached["response_json"] and cached["fetched_at"]
            and current - cached["fetched_at"] < CACHE_TTL_SECONDS and not force
        ):
            return json.loads(cached["response_json"]), cached["fetched_at"], True
        try:
            url = REPORT_URL + "?" + urlencode(full_params)
            last_error = None
            for attempt in range(3):
                try:
                    payload = youtube._authorized_json(account["id"], "GET", url, timeout=20)
                    last_error = None
                    break
                except youtube.YouTubeError as error:
                    last_error = error
                    reason = getattr(error, "reason", None)
                    if attempt == 2 or not getattr(error, "retryable", False) or reason in {"quotaExceeded", "dailyLimitExceeded"}:
                        raise
                    time.sleep(0.5 * (2 ** attempt))
            if last_error:
                raise last_error
            expected_columns = [
                *[name for name in full_params.get("dimensions", "").split(",") if name],
                *full_params["metrics"].split(","),
            ]
            parsed = parse_report(
                payload, full_params.get("startDate"), full_params.get("endDate"), expected_columns,
            )
            fetched_at = time.time()
            with connect() as conn:
                conn.execute(
                    "INSERT INTO youtube_analytics_cache(channel_id,query_key,query_json,response_json,actual_start_date,"
                    "actual_end_date,status,fetched_at,attempted_at,error_code,error_message) VALUES(?,?,?,?,?,?,'ok',?,?,NULL,NULL) "
                    "ON CONFLICT(channel_id,query_key) DO UPDATE SET query_json=excluded.query_json,response_json=excluded.response_json,"
                    "actual_start_date=excluded.actual_start_date,actual_end_date=excluded.actual_end_date,status='ok',"
                    "fetched_at=excluded.fetched_at,attempted_at=excluded.attempted_at,error_code=NULL,error_message=NULL",
                    (account["channel_id"], query_key, query_json, json.dumps(parsed), parsed["coverage"]["start_date"],
                     parsed["coverage"]["end_date"], fetched_at, fetched_at),
                )
            return parsed, fetched_at, False
        except youtube.YouTubeError as error:
            mapped = _provider_error(error)
            _save_failure(account["channel_id"], query_key, query_json, mapped)
            raise mapped from None
        except AnalyticsError as error:
            _save_failure(account["channel_id"], query_key, query_json, error)
            raise


def _report(rows, requested_start, requested_end, columns):
    days = [row["day"] for row in rows if isinstance(row.get("day"), str)]
    return {
        "rows": rows,
        "coverage": {"start_date": min(days) if days else None, "end_date": max(days) if days else None},
        "requested": {"start_date": requested_start, "end_date": requested_end},
        "columns": columns,
    }


def _query_day_range(account, params, *, force=False):
    start, end = date.fromisoformat(params["startDate"]), date.fromisoformat(params["endDate"])
    cursor, rows, synced, cached, columns = start, [], [], [], None
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=REPORT_PAGE_SIZE - 1), end)
        report, fetched_at, from_cache = _query(account, {
            **params, "startDate": cursor.isoformat(), "endDate": chunk_end.isoformat(),
            "maxResults": REPORT_PAGE_SIZE,
        }, force=force)
        rows.extend(report["rows"])
        columns = columns or report["columns"]
        synced.append(fetched_at)
        cached.append(from_cache)
        cursor = chunk_end + timedelta(days=1)
    rows.sort(key=lambda row: row.get("day", ""))
    return _report(rows, start.isoformat(), end.isoformat(), columns or []), max(synced), all(cached)


def _query_paginated(account, params, *, force=False, limit=VIDEO_REPORT_LIMIT):
    rows, synced, cached, columns = [], [], [], None
    start_index = 1
    while start_index <= limit:
        page_size = min(REPORT_PAGE_SIZE, limit - start_index + 1)
        report, fetched_at, from_cache = _query(account, {
            **params, "startIndex": start_index, "maxResults": page_size,
        }, force=force)
        rows.extend(report["rows"])
        columns = columns or report["columns"]
        synced.append(fetched_at)
        cached.append(from_cache)
        if len(report["rows"]) < page_size:
            break
        start_index += page_size
    return _report(rows, params.get("startDate"), params.get("endDate"), columns or []), max(synced), all(cached), len(rows) >= limit


def _combine_rows(rows, dimension, value):
    combined = {dimension: value}
    for metric in PRODUCTION_METRICS.split(","):
        if metric in {"averageViewDuration", "averageViewPercentage"}:
            combined[metric] = _weighted_average(rows, metric)
        else:
            combined[metric] = _metric_sum(rows, metric)
    return combined


def _attributed_report(account, video_ids, start, end, *, force=False):
    daily_rows, video_rows, synced, cached = {}, {}, [], []
    for video_id in video_ids:
        report, fetched_at, from_cache = _query_day_range(account, {
            "startDate": start, "endDate": end, "metrics": VIDEO_METRICS,
            "dimensions": "day", "sort": "day", "filters": f"video=={video_id}",
        }, force=force)
        synced.append(fetched_at)
        cached.append(from_cache)
        by_day = {}
        for row in report["rows"]:
            by_day.setdefault(row["day"], []).append(row)
            daily_rows.setdefault(row["day"], []).append(row)
        video_rows[video_id] = [_combine_rows(rows, "video", video_id) for rows in by_day.values()]
    trend = [
        _combine_rows(rows, "day", day)
        for day, rows in sorted(daily_rows.items())
    ]
    videos = [
        _combine_rows(video_rows[video_id], "video", video_id)
        for video_id in video_ids if video_rows.get(video_id)
    ]
    report = _report(trend, start, end, ["day", *VIDEO_METRICS.split(",")])
    return report, videos, max(synced, default=None), all(cached) if cached else True


def _save_failure(channel_id, query_key, query_json, error):
    timestamp = time.time()
    with connect() as conn:
        cached = conn.execute(
            "SELECT response_json,fetched_at FROM youtube_analytics_cache WHERE channel_id=? AND query_key=?",
            (channel_id, query_key),
        ).fetchone()
        if cached and cached["response_json"] and cached["fetched_at"]:
            conn.execute(
                "UPDATE youtube_analytics_cache SET query_json=?,status='ok',attempted_at=?,error_code=?,error_message=? "
                "WHERE channel_id=? AND query_key=?",
                (query_json, timestamp, error.code, str(error), channel_id, query_key),
            )
            return
        conn.execute(
            "INSERT INTO youtube_analytics_cache(channel_id,query_key,query_json,status,attempted_at,error_code,error_message) "
            "VALUES(?,?,?,'failed',?,?,?) ON CONFLICT(channel_id,query_key) DO UPDATE SET query_json=excluded.query_json,"
            "status='failed',attempted_at=excluded.attempted_at,error_code=excluded.error_code,error_message=excluded.error_message",
            (channel_id, query_key, query_json, timestamp, error.code, str(error)),
        )


def _publications(account_id):
    with connect() as conn:
        count = conn.execute(
            "SELECT COUNT(DISTINCT video_id) AS count FROM youtube_publications "
            "WHERE account_id=? AND status='published' AND video_id IS NOT NULL", (account_id,),
        ).fetchone()["count"]
        rows = conn.execute(
            "SELECT id,video_id,video_url,title,clip_title,content_type,published_at,created_at,attribution_json "
            "FROM youtube_publications WHERE account_id=? AND status='published' AND video_id IS NOT NULL "
            "ORDER BY COALESCE(published_at,created_at) DESC LIMIT 500", (account_id,),
        ).fetchall()
    videos = {}
    for row in rows:
        item = dict(row)
        item["attribution"] = json.loads(item.pop("attribution_json")) if item.get("attribution_json") else None
        item["published_date"] = item["published_at"][:10] if item.get("published_at") else None
        videos.setdefault(item["video_id"], item)
    return videos, count


def _metric_sum(rows, name):
    values = [row[name] for row in rows if isinstance(row.get(name), (int, float)) and math.isfinite(row[name])]
    return sum(values) if values else None


def _weighted_average(rows, metric):
    values = [(row.get(metric), row.get("views")) for row in rows]
    values = [(value, weight) for value, weight in values if isinstance(value, (int, float)) and isinstance(weight, (int, float)) and weight > 0]
    denominator = sum(weight for _, weight in values)
    return sum(value * weight for value, weight in values) / denominator if denominator else None


def _summary(rows, include_subscribers):
    metrics = {
        "views": _metric_sum(rows, "views"),
        "engaged_views": _metric_sum(rows, "engagedViews"),
        "estimated_minutes_watched": _metric_sum(rows, "estimatedMinutesWatched"),
        "average_view_duration": _weighted_average(rows, "averageViewDuration"),
        "average_view_percentage": _weighted_average(rows, "averageViewPercentage"),
        "likes": _metric_sum(rows, "likes"),
        "comments": _metric_sum(rows, "comments"),
        "shares": _metric_sum(rows, "shares"),
    }
    if include_subscribers:
        gained = _metric_sum(rows, "subscribersGained")
        lost = _metric_sum(rows, "subscribersLost")
        metrics.update({"subscribers_gained": gained, "subscribers_lost": lost,
                        "net_subscribers": gained - lost if gained is not None and lost is not None else None})
    else:
        metrics.update({"subscribers_gained": None, "subscribers_lost": None, "net_subscribers": None})
    return metrics


def _metric_changes(current, previous):
    changes = {}
    for key, value in current.items():
        old = previous.get(key)
        if not isinstance(value, (int, float)) or not isinstance(old, (int, float)):
            changes[key] = {"absolute": None, "percent": None}
            continue
        absolute = value - old
        changes[key] = {"absolute": absolute, "percent": absolute / abs(old) * 100 if old else None}
    return changes


def _duration_group(seconds):
    if not isinstance(seconds, (int, float)):
        return "Unavailable"
    if seconds < 20:
        return "Under 20s"
    if seconds <= 35:
        return "20–35s"
    return "Over 35s"


def build_insights(videos, start_date, end_date):
    attributed = [video for video in videos if video.get("attribution")]
    count = len(attributed)
    if count < MIN_INSIGHT_SAMPLE:
        return {"minimum_sample": MIN_INSIGHT_SAMPLE, "sample_count": count, "items": [],
                "message": "Belum cukup data untuk membuat insight yang andal."}
    items = [{"kind": "sample", "sample_count": count, "timeframe": f"{start_date}–{end_date}",
              "message": f"{count} video Klipnara dengan data Analytics masuk dalam periode ini."}]
    for field, label, value_key in (
        ("base_workflow", "workflow", "engagedViews"),
        ("subtitle_type", "subtitle", "averageViewPercentage"),
    ):
        groups = {}
        for video in attributed:
            value = video.get(value_key)
            key = video["attribution"].get(field) or "Unavailable"
            if isinstance(value, (int, float)):
                groups.setdefault(key, []).append(value)
        qualified = [(key, statistics.median(values), len(values)) for key, values in groups.items() if len(values) >= MIN_INSIGHT_SAMPLE]
        if len(qualified) < 2:
            continue
        qualified.sort(key=lambda item: item[1], reverse=True)
        best, second = qualified[0], qualified[1]
        if best[1] <= second[1]:
            continue
        unit = "Engaged Views" if value_key == "engagedViews" else "Average View Percentage"
        best_value = f"{best[1]:.1f}" if value_key == "engagedViews" else f"{best[1]:.1f}%"
        second_value = f"{second[1]:.1f}" if value_key == "engagedViews" else f"{second[1]:.1f}%"
        items.append({
            "kind": "comparison", "sample_count": best[2] + second[2], "timeframe": f"{start_date}–{end_date}",
            "metric": unit,
            "message": f"Pada periode ini, kelompok {best[0]} memiliki median {unit} {best_value} (n={best[2]}) vs {second_value} (n={second[2]}) untuk {second[0]}.",
        })
    return {"minimum_sample": MIN_INSIGHT_SAMPLE, "sample_count": count, "items": items,
            "message": None if len(items) > 1 else "Belum cukup data lintas kelompok untuk insight performa yang andal."}


def dashboard(account_id, scope="channel", start_date=None, end_date=None, force=False):
    if scope not in {"channel", "klipnara"}:
        raise AnalyticsError("analytics_scope_invalid", "Pilih cakupan Channel atau Klipnara.", 422)
    start, end = date_range(start_date, end_date)
    account = _account(account_id)
    publications, published_video_count = _publications(account_id)
    video_ids = sorted(publications)
    metrics = CHANNEL_METRICS if scope == "channel" else PRODUCTION_METRICS
    daily_params = {"startDate": start, "endDate": end, "metrics": metrics, "dimensions": "day", "sort": "day"}
    attributed_videos = None
    if scope == "klipnara":
        if not video_ids:
            daily = {"rows": [], "coverage": {"start_date": None, "end_date": None}}
            daily_synced, daily_cache = None, True
        else:
            daily, attributed_videos, daily_synced, daily_cache = _attributed_report(
                account, video_ids, start, end, force=force,
            )
    else:
        daily, daily_synced, daily_cache = _query_day_range(account, daily_params, force=force)
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    previous_end = date.fromisoformat(start) - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    previous_metrics = None
    previous_period = {"start_date": previous_start.isoformat(), "end_date": previous_end.isoformat()}
    previous_synced = None
    previous_cache = True
    comparison_error = None
    if scope != "klipnara" or video_ids:
        previous_params = {**daily_params, "startDate": previous_period["start_date"], "endDate": previous_period["end_date"]}
        try:
            if scope == "klipnara":
                previous_report, _previous_videos, previous_synced, previous_cache = _attributed_report(
                    account, video_ids, previous_period["start_date"], previous_period["end_date"], force=force,
                )
            else:
                previous_report, previous_synced, previous_cache = _query_day_range(account, previous_params, force=force)
            previous_metrics = _summary(previous_report["rows"], include_subscribers=scope == "channel")
        except AnalyticsError as error:
            comparison_error = {"code": error.code, "message": str(error)}
    elif scope == "klipnara":
        previous_metrics = None
    video_report = {"rows": [], "coverage": {"start_date": None, "end_date": None}}
    video_synced, video_cache, video_error = None, True, None
    channel_video_limit_reached = False
    video_params = {"startDate": start, "endDate": end, "metrics": VIDEO_METRICS,
                    "dimensions": "video", "sort": "-views"}
    if scope == "klipnara":
        if video_ids:
            video_report = {"rows": attributed_videos or [], "coverage": daily["coverage"]}
            video_synced, video_cache = daily_synced, daily_cache
    else:
        try:
            video_report, video_synced, video_cache, channel_video_limit_reached = _query_paginated(
                account, video_params, force=force,
            )
        except AnalyticsError as error:
            video_error = {"code": error.code, "message": str(error)}
    videos = []
    for row in video_report["rows"]:
        video_id = row.get("video")
        if not isinstance(video_id, str) or (scope == "klipnara" and video_id not in publications):
            continue
        publication = publications.get(video_id)
        attribution = publication.get("attribution") if publication else None
        videos.append({
            **row,
            "video_id": video_id,
            "publication_id": publication.get("id") if publication else None,
            "title": publication.get("title") if publication else None,
            "content_title": publication.get("clip_title") if publication else None,
            "published_at": publication.get("published_at") if publication else None,
            "published_date": publication.get("published_date") if publication else None,
            "video_url": publication.get("video_url") if publication else f"https://youtu.be/{video_id}",
            "attribution": attribution,
            "attribution_available": bool(attribution),
        })
    rows = daily["rows"]
    last_sync = max((value for value in (daily_synced, previous_synced, video_synced) if value), default=None)
    errors = {"videos": video_error} if video_error else {}
    if comparison_error:
        errors["comparison"] = comparison_error
    summary = _summary(rows, include_subscribers=scope == "channel")
    return {
        "channel": {"id": account["channel_id"], "title": account["channel_title"]},
        "scope": scope,
        "requested": {"start_date": start, "end_date": end},
        "coverage": daily.get("coverage", {"start_date": None, "end_date": None}),
        "metrics": summary,
        "comparison": {
            "previous_period": previous_period,
            "metrics": previous_metrics,
            "changes": _metric_changes(summary, previous_metrics) if previous_metrics is not None else None,
            "cached": previous_cache,
        },
        "trend": rows,
        "videos": videos,
        "insights": build_insights(videos, start, end) if scope == "klipnara" else None,
        "last_synced_at": datetime.fromtimestamp(last_sync, timezone.utc).isoformat() if last_sync else None,
        "cached": daily_cache and previous_cache and video_cache,
        "errors": errors,
        "channel_video_limit_reached": channel_video_limit_reached,
        "attribution": {"published_video_count": published_video_count, "reported_video_count": len(videos),
                        "limit_reached": published_video_count > 500},
        "metric_definitions": {"views": "views", "engaged_views": "engagedViews"},
    }


def video_detail(publication_id, start_date=None, end_date=None, force=False):
    start, end = date_range(start_date, end_date)
    with connect() as conn:
        publication = conn.execute(
            "SELECT p.*,a.id AS account_id,a.channel_id,a.channel_title,a.status AS account_status,"
            "a.token_blob,a.verified_at,a.granted_scopes_json FROM youtube_publications p "
            "JOIN youtube_accounts a ON a.id=p.account_id WHERE p.id=?", (publication_id,),
        ).fetchone()
    if not publication:
        raise AnalyticsError("analytics_publication_not_found", "Riwayat publikasi Klipnara tidak ditemukan.", 404)
    if publication["status"] != "published" or not publication["video_id"]:
        raise AnalyticsError("analytics_not_published", "Video belum dipublikasikan atau YouTube belum mengonfirmasi publikasi.", 409)
    account = _account(publication["account_id"])
    video_id = publication["video_id"]
    report, fetched_at, cached = _query_day_range(account, {
        "startDate": start, "endDate": end, "metrics": VIDEO_METRICS, "dimensions": "day",
        "filters": f"video=={video_id}", "sort": "day",
    }, force=force)
    rows = report["rows"]
    item = dict(publication)
    attribution = json.loads(item["attribution_json"]) if item.get("attribution_json") else None
    return {
        "publication_id": publication_id, "video_id": video_id, "title": item["title"],
        "content_title": item["clip_title"], "video_url": item["video_url"],
        "published_at": item["published_at"], "duration": item["duration"], "attribution": attribution,
        "requested": {"start_date": start, "end_date": end}, "coverage": report["coverage"],
        "metrics": _summary(rows, include_subscribers=False), "trend": rows,
        "last_synced_at": datetime.fromtimestamp(fetched_at, timezone.utc).isoformat(), "cached": cached,
    }


def retention(publication_id, start_date=None, end_date=None, force=False):
    start, end = date_range(start_date, end_date)
    with connect() as conn:
        publication = conn.execute(
            "SELECT p.id,p.account_id,p.video_id,p.duration,p.status,p.published_at FROM youtube_publications p WHERE p.id=?",
            (publication_id,),
        ).fetchone()
    if not publication:
        raise AnalyticsError("analytics_publication_not_found", "Riwayat publikasi Klipnara tidak ditemukan.", 404)
    if publication["status"] != "published" or not publication["video_id"]:
        raise AnalyticsError("analytics_not_published", "Retensi tersedia setelah YouTube mengonfirmasi publikasi.", 409)
    account = _account(publication["account_id"])
    report, fetched_at, cached = _query(account, {
        "startDate": start, "endDate": end, "metrics": RETENTION_METRICS,
        "dimensions": "elapsedVideoTimeRatio", "filters": f"video=={publication['video_id']}",
        "sort": "elapsedVideoTimeRatio",
    }, force=force)
    points = [{
        "ratio": row["elapsedVideoTimeRatio"],
        "timestamp_seconds": row["elapsedVideoTimeRatio"] * publication["duration"],
        "audience_watch_ratio": row.get("audienceWatchRatio"),
        "relative_retention_performance": row.get("relativeRetentionPerformance"),
    } for row in report["rows"]]
    return {
        "publication_id": publication_id, "video_id": publication["video_id"],
        "duration": publication["duration"], "requested": {"start_date": start, "end_date": end},
        "points": points,
        "last_synced_at": datetime.fromtimestamp(fetched_at, timezone.utc).isoformat(), "cached": cached,
        "message": None if points else "Belum ada data audience retention untuk video dan periode ini.",
    }
