const { spawn } = require("node:child_process");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const backend = path.join(root, "backend");
const python = path.join(backend, ".venv", "Scripts", "python.exe");
const child = spawn(python, [
  "-m", "uvicorn", "clipper.main:app",
  "--host", "127.0.0.1", "--port", "8000", "--env-file", ".env",
], {
  cwd: backend,
  env: { ...process.env, PYTHONUNBUFFERED: "1" },
  stdio: "inherit",
  windowsHide: false,
});

let stopping = false;
let fallback;

function stop(signal) {
  if (stopping) return;
  stopping = true;
  if (child.exitCode === null) {
    child.kill(signal);
    fallback = setTimeout(() => {
      if (child.exitCode === null) child.kill("SIGTERM");
    }, 5000);
    fallback.unref();
  }
}

process.on("SIGINT", () => stop("SIGINT"));
process.on("SIGTERM", () => stop("SIGTERM"));
process.on("SIGBREAK", () => stop("SIGINT"));

child.on("error", (error) => {
  console.error(`[BACKEND] Could not start Uvicorn: ${error.message}`);
  process.exitCode = 1;
});

child.on("exit", (code, signal) => {
  if (fallback) clearTimeout(fallback);
  process.exitCode = code ?? (stopping && signal ? 0 : 1);
});
