const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = path.resolve(__dirname, "..");
const backend = path.join(root, "backend");
const frontend = path.join(root, "frontend");
const python = path.join(backend, ".venv", "Scripts", "python.exe");

function fail(message) {
  console.error(`[Klipnara dev] ${message}`);
  process.exit(1);
}

const target = process.argv[2] || "all";
if (["all", "backend"].includes(target)) {
  if (!fs.existsSync(python)) {
    fail("Backend virtual environment missing. Create it with `python -m venv backend/.venv`, then install `backend/requirements-dev.txt`.");
  }
  if (!fs.existsSync(path.join(backend, ".env"))) {
    fail("backend/.env missing. Run `Copy-Item backend/.env.example backend/.env`, edit local tool paths, then retry.");
  }
  const imports = spawnSync(python, ["-c", "import fastapi, uvicorn, multipart"], { cwd: backend, stdio: "ignore", windowsHide: true });
  if (imports.error || imports.status !== 0) {
    fail("Backend Python dependencies are missing. Run `backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt`.");
  }
}

if (["all", "frontend"].includes(target)) {
  if (!fs.existsSync(path.join(frontend, "node_modules", "next"))) {
    fail("Frontend dependencies are missing. Run `npm --prefix frontend install`.");
  }
}

if (target === "all" && !fs.existsSync(path.join(root, "node_modules", "concurrently"))) {
  fail("Root development runner dependency is missing. Run `npm install` from the repository root.");
}
