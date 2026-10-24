export const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
export type ReviewStatus = "needs_review" | "approved" | "needs_revision";

export function reviewStatusLabel(status: ReviewStatus) {
  return status === "approved" ? "Disetujui" : status === "needs_revision" ? "Perlu Revisi" : "Perlu Review";
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
    throw new Error(data?.detail || `Request gagal (${response.status}).`);
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
