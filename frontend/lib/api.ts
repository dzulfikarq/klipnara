export const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
export type ReviewStatus = "needs_review" | "approved" | "needs_revision";

export function reviewStatusLabel(status: ReviewStatus) {
  return status === "approved" ? "Disetujui" : status === "needs_revision" ? "Perlu Revisi" : "Perlu Review";
}

function formatErrorDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const issues = detail.filter((item): item is { loc?: unknown[]; msg?: unknown; type?: unknown } => Boolean(item) && typeof item === "object");
    const moodFields = new Set(["text_mode", "segments", "segments_source", "gradient_opacity", "auto_contrast", "font_weight", "visual", "offset", "muted"]);
    const staleMoodSchema = issues.some((issue) => Array.isArray(issue.loc)
      && issue.type === "extra_forbidden"
      && issue.loc.includes("composition")
      && issue.loc.some((part) => moodFields.has(String(part))));
    if (staleMoodSchema) {
      return "Backend AI Mood Quotes memakai schema lama. Restart backend dari workspace terbaru, lalu muat ulang halaman.";
    }
    const messages = issues.map((issue) => {
      const location = Array.isArray(issue.loc) ? issue.loc.filter((part) => part !== "body").join(".") : "";
      const message = typeof issue.msg === "string" ? issue.msg : "Input tidak valid.";
      return location ? `${location}: ${message}` : message;
    });
    return messages.join("; ") || JSON.stringify(detail);
  }
  if (detail && typeof detail === "object") {
    const message = (detail as { message?: unknown }).message;
    return typeof message === "string" ? message : JSON.stringify(detail);
  }
  return "Request gagal.";
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`${API}/api${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    throw new Error("Backend tidak terhubung. Jalankan FastAPI di 127.0.0.1:8000.");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = formatErrorDetail(data?.detail);
    throw new Error(detail === "Request gagal." ? `Request gagal (${response.status}).` : detail);
  }
  return response.json();
}

export function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

export function formatBytes(bytes: number) {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${(bytes / 1024 ** 2).toFixed(0)} MB`;
}
