export function parseTimestamp(value) {
  const parts = value.trim().split(":");
  if (parts.length < 2 || parts.length > 3 || parts.some((part) => !/^\d+$/.test(part))) return null;
  const numbers = parts.map(Number);
  if (numbers.some((part) => !Number.isSafeInteger(part)) || numbers.at(-1) >= 60) return null;
  if (numbers.length === 2) {
    const total = numbers[0] * 60 + numbers[1];
    return Number.isSafeInteger(total) ? total : null;
  }
  if (numbers[1] >= 60) return null;
  const total = numbers[0] * 3600 + numbers[1] * 60 + numbers[2];
  return Number.isSafeInteger(total) ? total : null;
}

const YOUTUBE_HOSTS = new Set(["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"]);
export const YOUTUBE_METADATA_PATH = "/youtube-clips/metadata";

export function isYouTubeMetadataRouteNotFound(status, path) {
  return status === 404 && path === YOUTUBE_METADATA_PATH;
}

export function quickClipYouTubeReference(info) {
  return info.metadata_status === "route_not_found"
    ? null
    : { canonical_url: info.canonical_url, video_id: info.video_id };
}

function parseUrlTimestamp(value) {
  if (/^\d+$/.test(value)) {
    const seconds = Number(value);
    return Number.isSafeInteger(seconds) ? seconds : null;
  }
  if (value.includes(":")) return parseTimestamp(value);
  const match = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/i.exec(value);
  if (!match || !match.slice(1).some(Boolean)) return null;
  const [hours, minutes, seconds] = match.slice(1).map((part) => Number(part || 0));
  if (seconds >= 60 || (hours > 0 && minutes >= 60)) return null;
  const total = hours * 3600 + minutes * 60 + seconds;
  return Number.isSafeInteger(total) ? total : null;
}

export function parseYouTubeUrl(value) {
  if (typeof value !== "string" || !value.trim() || value.length > 2048 || /[\u0000-\u001f]/.test(value)) return null;
  let raw = value.trim();
  if (!/^[a-z][a-z\d+.-]*:/i.test(raw)) raw = `https://${raw}`;
  const authority = /^[a-z][a-z\d+.-]*:\/\/([^/?#]*)/i.exec(raw)?.[1] || "";
  let url;
  try { url = new URL(raw); } catch { return null; }
  const hostname = url.hostname.toLowerCase();
  if (!new Set(["http:", "https:"]).has(url.protocol) || !YOUTUBE_HOSTS.has(hostname) || url.username || url.password || url.port || /:\d+$/.test(authority)) return null;

  const path = url.pathname.replace(/\/+$/, "");
  let videoId = null;
  if (hostname === "youtu.be") {
    const match = /^\/([A-Za-z0-9_-]{11})$/.exec(path);
    videoId = match?.[1] || null;
  } else if (path === "/watch") {
    const ids = url.searchParams.getAll("v");
    videoId = ids.length === 1 ? ids[0] : null;
  } else {
    const match = /^\/shorts\/([A-Za-z0-9_-]{11})$/.exec(path);
    videoId = match?.[1] || null;
  }
  if (!videoId || !/^[A-Za-z0-9_-]{11}$/.test(videoId)) return null;

  let startSeconds = null;
  for (const key of ["t", "start"]) {
    const values = url.searchParams.getAll(key);
    if (values.length === 1) {
      startSeconds = parseUrlTimestamp(values[0]);
      if (startSeconds !== null) break;
    }
  }
  return {
    video_id: videoId,
    canonical_url: `https://www.youtube.com/watch?v=${videoId}`,
    start_seconds: startSeconds,
  };
}

export function formatTimestamp(value) {
  const total = Math.max(0, Math.floor(value));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function validateClipRange(start, end, duration = null) {
  const durationKnown = Number.isFinite(duration) && duration > 0;
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0) return { valid: false, reason: "invalid", durationKnown };
  if (end <= start) return { valid: false, reason: "order", durationKnown };
  if (durationKnown && end > duration) return { valid: false, reason: "duration", durationKnown };
  return { valid: true, reason: null, durationKnown, selectedDuration: end - start };
}

export function youtubePlayerErrorMessage(code) {
  if (code === 2) return "YouTube menolak parameter preview. Periksa URL dan ID video.";
  if (code === 5) return "Player YouTube gagal memutar video pada browser ini.";
  if (code === 100) return "Video tidak tersedia, privat, dihapus, atau dibatasi pemilik.";
  if (code === 101 || code === 150) return "Pemilik video menonaktifkan embedded preview.";
  if (code === 153) return "YouTube tidak dapat memverifikasi identitas pemanggil player.";
  return "Player YouTube gagal dimuat. Coba lagi atau periksa pembatasan embed/jaringan.";
}
