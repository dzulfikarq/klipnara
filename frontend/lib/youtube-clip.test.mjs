import assert from "node:assert/strict";
import test from "node:test";
import { formatTimestamp, isYouTubeMetadataRouteNotFound, parseTimestamp, parseYouTubeUrl, quickClipYouTubeReference, validateClipRange, youtubePlayerErrorMessage } from "./youtube-clip.mjs";

test("parses and formats Quick Clip timestamps", () => {
  assert.equal(parseTimestamp("14:09"), 849);
  assert.equal(parseTimestamp("1:02:03"), 3723);
  assert.equal(parseTimestamp("02:60"), null);
  assert.equal(parseTimestamp("1:60:00"), null);
  assert.equal(parseTimestamp("00:xx"), null);
  assert.equal(parseTimestamp("9007199254740991:00:00"), null);
  assert.equal(formatTimestamp(3723), "1:02:03");
});

test("normalizes requested YouTube URLs without mistaking tracking data for video ID", () => {
  const short = parseYouTubeUrl("https://youtu.be/Zz7os_kWwnM?si=K1t7XMIZuDy10liL");
  const watch = parseYouTubeUrl("https://www.youtube.com/watch?v=Zz7os_kWwnM");
  assert.equal(short?.video_id, "Zz7os_kWwnM");
  assert.equal(watch?.video_id, short?.video_id);
  assert.equal(short?.canonical_url, "https://www.youtube.com/watch?v=Zz7os_kWwnM");
  assert.equal(parseYouTubeUrl("youtube.com/watch?v=Zz7os_kWwnM&si=tracking&t=1m2s")?.start_seconds, 62);
  assert.equal(parseYouTubeUrl("https://youtube.com.evil.example/watch?v=Zz7os_kWwnM"), null);
  assert.equal(parseYouTubeUrl("https://youtube.com:443/watch?v=Zz7os_kWwnM"), null);
});

test("distinguishes missing metadata route from YouTube metadata failure", () => {
  assert.equal(isYouTubeMetadataRouteNotFound(404, "/youtube-clips/metadata"), true);
  assert.equal(isYouTubeMetadataRouteNotFound(404, "/sources/unknown"), false);
  assert.equal(isYouTubeMetadataRouteNotFound(200, "/youtube-clips/metadata"), false);
  assert.equal(quickClipYouTubeReference({ metadata_status: "route_not_found", canonical_url: "https://www.youtube.com/watch?v=Zz7os_kWwnM", video_id: "Zz7os_kWwnM" }), null);
  assert.deepEqual(quickClipYouTubeReference({ metadata_status: "not_configured", canonical_url: "https://www.youtube.com/watch?v=Zz7os_kWwnM", video_id: "Zz7os_kWwnM" }), {
    canonical_url: "https://www.youtube.com/watch?v=Zz7os_kWwnM", video_id: "Zz7os_kWwnM",
  });
});

test("validates selected ranges with known and unknown duration", () => {
  assert.equal(validateClipRange(10, 20, 30).valid, true);
  assert.deepEqual(validateClipRange(20, 20, null), { valid: false, reason: "order", durationKnown: false });
  assert.equal(validateClipRange(10, 20, null).durationKnown, false);
  assert.deepEqual(validateClipRange(10, 31, 30), { valid: false, reason: "duration", durationKnown: true });
  assert.equal(validateClipRange(0, -1, null).reason, "order");
});

test("maps IFrame API unavailable and embed errors to actionable messages", () => {
  assert.match(youtubePlayerErrorMessage(100), /tidak tersedia/);
  assert.match(youtubePlayerErrorMessage(101), /menonaktifkan/);
  assert.match(youtubePlayerErrorMessage(150), /menonaktifkan/);
  assert.match(youtubePlayerErrorMessage(153), /memverifikasi/);
  assert.match(youtubePlayerErrorMessage(999), /gagal dimuat/);
});
