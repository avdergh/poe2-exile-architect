import { spawn, spawnSync } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";


const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const pluginRoot = path.dirname(scriptDir);
const pythonScript = path.join(scriptDir, "run_plugin_server.py");
const codexPython = path.join(
  os.homedir(),
  ".cache",
  "codex-runtimes",
  "codex-primary-runtime",
  "dependencies",
  "python",
  process.platform === "win32" ? "python.exe" : "bin/python",
);
const candidates = [
  process.env.POE_BD_CREATOR_PYTHON,
  codexPython,
  process.platform === "win32" ? "python.exe" : "python3",
  "python",
].filter(Boolean);

let python = null;
for (const candidate of [...new Set(candidates)]) {
  const probe = spawnSync(candidate, ["--version"], {
    cwd: pluginRoot,
    encoding: "utf8",
    windowsHide: true,
  });
  if (!probe.error && probe.status === 0) {
    python = candidate;
    break;
  }
}

if (!python) {
  process.stderr.write(
    "poe-bd-creator could not find Python. Set POE_BD_CREATOR_PYTHON to Python 3.11+.\n",
  );
  process.exit(1);
}

const child = spawn(python, [pythonScript, ...process.argv.slice(2)], {
  cwd: pluginRoot,
  env: { ...process.env, PYTHONUTF8: "1" },
  stdio: "inherit",
  windowsHide: true,
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    if (!child.killed) child.kill(signal);
  });
}

child.on("error", (error) => {
  process.stderr.write(`poe-bd-creator failed to start Python: ${error.message}\n`);
  process.exit(1);
});
child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});
