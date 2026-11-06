import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { repairSourceNativeLibraries } from "../electron/scripts/native-compat.mjs";
import {
  selectTorchVariant,
  torchSyncArgs,
  windowsRocmSyncArgs,
} from "../electron/scripts/torch-variant.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * Wheels pinned to direct github.com release URLs in uv.lock (no package
 * index in between). These are the only sync inputs uv cannot fetch from
 * PyPI, so they are the ones that die when github.com or its release CDN
 * (objects.githubusercontent.com) is unreachable — which is common on
 * corporate, firewalled and some regional networks. Every other dependency
 * downloads from PyPI and keeps working.
 */
export function githubDirectWheels(lockText) {
  const wheels = [];
  for (const block of lockText.split(/\n(?=\[\[package\]\])/)) {
    const name = block.match(/^name = "([^"]+)"$/m)?.[1];
    const sourceUrl = block.match(/^source = \{ url = "([^"]+)" \}$/m)?.[1];
    if (!name || !sourceUrl || !sourceUrl.startsWith("https://github.com/")) continue;
    const wheel = block.match(/\{ url = "([^"]+)", hash = "sha256:([0-9a-f]{64})"/);
    if (!wheel) continue;
    wheels.push({ name, url: sourceUrl, sha256: wheel[2] });
  }
  return wheels;
}

export function sha256File(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

/**
 * Candidate download URLs for a release asset: the canonical URL first,
 * then mirror prefixes (proxy services that front github.com release
 * downloads; common on networks where the release CDN is throttled).
 * A compromised mirror cannot poison the install because every file is
 * sha256-checked against the hash pinned in uv.lock before it is used.
 * Override with OMNIVOICE_GH_MIRRORS (comma-separated prefixes, "" = off).
 */
export function wheelSourceUrls(url, env = process.env) {
  const raw = env.OMNIVOICE_GH_MIRRORS;
  const mirrors =
    raw === undefined
      ? ["https://gh-proxy.com", "https://ghproxy.net"]
      : raw
          .split(",")
          .map((prefix) => prefix.trim().replace(/\/+$/, ""))
          .filter(Boolean);
  return [url, ...mirrors.map((prefix) => `${prefix}/${url}`)];
}

function downloadFile({ run, platform, url, destination }) {
  // Windows ships curl.exe since 10 1803; naming the .exe sidesteps any
  // PowerShell "curl" alias that spawnSync would otherwise trip over.
  const curl = platform === "win32" ? "curl.exe" : "curl";
  const result = run(
    curl,
    ["-fL", "--connect-timeout", "20", "--max-time", "300", "--silent", "--show-error", "-o", destination, url],
    { stdio: ["ignore", "ignore", "inherit"] },
  );
  if (result.error || (result.status ?? 1) !== 0) return false;
  return existsSync(destination) && statSync(destination).size > 0;
}

/**
 * Best-effort: fetch the direct-URL wheels that `uv sync` could not
 * download, checksum them against uv.lock, and install them into the venv
 * so a later `uv sync --locked` finds them satisfied. Idempotent — a wheel
 * already in the local cache and matching the pinned hash is reused.
 */
export async function seedGithubWheels({
  wheels,
  run,
  env = process.env,
  platform = process.platform,
  log = console.log,
} = {}) {
  if (env.OMNIVOICE_SEED_WHEELS === "0" || wheels.length === 0) return [];
  const cacheDir = resolve(root, ".omnivoice-cache", "wheels");
  mkdirSync(cacheDir, { recursive: true });
  const venvPython = resolve(
    root,
    ".venv",
    ...(platform === "win32" ? ["Scripts", "python.exe"] : ["bin", "python"]),
  );
  const seeded = [];
  for (const wheel of wheels) {
    const destination = resolve(cacheDir, wheel.url.split("/").pop());
    let fetched = existsSync(destination) && statSync(destination).size > 0 && sha256File(destination) === wheel.sha256;
    if (fetched) {
      log(`[setup] ${wheel.name}: reusing the cached local wheel`);
    } else {
      for (const url of wheelSourceUrls(wheel.url, env)) {
        log(`[setup] fetching ${wheel.name} outside uv (github.com was unreachable during sync)…`);
        if (downloadFile({ run, platform, url, destination })) {
          const digest = sha256File(destination);
          if (digest === wheel.sha256) {
            fetched = true;
            break;
          }
          log(`[setup] ${wheel.name}: checksum mismatch (${digest.slice(0, 12)}…) — discarding and trying the next source`);
          rmSync(destination, { force: true });
        }
      }
    }
    if (!fetched) {
      log(`[setup] ${wheel.name}: could not download from github.com or mirrors — continuing without it`);
      continue;
    }
    if (!existsSync(venvPython)) {
      const created = run("uv", ["venv"], { cwd: root, env, stdio: "inherit" });
      if ((created.status ?? 1) !== 0) continue;
    }
    const install = run("uv", ["pip", "install", "--python", venvPython, destination], {
      cwd: root,
      env,
      stdio: "inherit",
    });
    if ((install.status ?? 1) === 0) {
      seeded.push(wheel.name);
      log(`[setup] ${wheel.name}: installed from the local copy`);
    }
  }
  return seeded;
}

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

/**
 * `uv sync --locked` hardened for networks where github.com's release CDN
 * drops or refuses connections. uv already retries three times, but those
 * land inside the same short window and fail together (scripts/uv-sync-retry.sh
 * documents the same failure in CI), so retrying whole attempts is what
 * actually clears it. Ladder:
 *   1. plain attempts with growing backoff (OMNIVOICE_SYNC_ATTEMPTS,
 *      default 3);
 *   2. one attempt after best-effort seeding the direct-URL wheels from the
 *      canonical URL or mirrors;
 *   3. a final attempt excluding the direct-URL wheels, so a missing
 *      phonemizer model can never block the whole backend from starting.
 */
export async function uvSyncResilient({
  run,
  env = process.env,
  syncArgs = [],
  log = console.log,
} = {}) {
  const plain = ["sync", "--locked", ...syncArgs];
  const attempts = Math.max(1, Number(env.OMNIVOICE_SYNC_ATTEMPTS || 3));
  const backoffs = (env.OMNIVOICE_SYNC_BACKOFF_MS || "10000,30000")
    .split(",")
    .map((value) => Number(value.trim()) || 0);
  const direct = githubDirectWheels(readFileSync(resolve(root, "uv.lock"), "utf8"));
  const steps = [];
  for (let index = 0; index < attempts; index += 1)
    steps.push({ args: plain, backoff: backoffs[index] ?? backoffs.at(-1) ?? 0 });
  steps.push({ args: plain, seed: true });
  const excluded = direct.map((wheel) => wheel.name);
  const reduced =
    direct.length > 0
      ? [...plain, ...excluded.flatMap((name) => ["--no-install-package", name])]
      : null;
  if (reduced) steps.push({ args: reduced, reduced: true });

  for (const step of steps) {
    if (step.seed) await seedGithubWheels({ wheels: direct, run, env, log });
    const result = run("uv", step.args, { cwd: root, env, stdio: "inherit" });
    if (result.error) throw result.error;
    if ((result.status ?? 1) === 0) {
      if (step.reduced) {
        // The reduced sync strips anything it could not verify, so put back
        // whatever the seeding stage managed to fetch (pure local work —
        // no network — when the wheel file is already cached).
        log(`[setup] synced without ${excluded.join(", ")} — run \`bun run dev\` again later with github.com reachable to pick them up`);
        await seedGithubWheels({ wheels: direct, run, env, log });
      }
      return 0;
    }
    if (step.backoff) {
      log(`[setup] uv sync failed — retrying in ${Math.round(step.backoff / 1000)}s${step.reduced ? " (without the extras)" : ""}`);
      await sleep(step.backoff);
    }
  }
  log(
    "[setup] uv sync failed after retries. If the log above shows a github.com download error" +
      " (for example en-core-web-sm), check connectivity to github.com, or point" +
      " OMNIVOICE_GH_MIRRORS at a mirror prefix that works on your network, then run again.",
  );
  return 1;
}

export async function setupApi({
  env = process.env,
  platform = process.platform,
  arch = process.arch,
  run = spawnSync,
  selectVariant = selectTorchVariant,
  log = console.log,
  repairNativeLibraries = repairSourceNativeLibraries,
} = {}) {
  // PyTorch publishes no Intel-Mac wheels, so the locked sync can only fail
  // part-way and leave an environment the app reports as incomplete (#3584).
  if (platform === "darwin" && arch === "x64")
    throw new Error(
      "Intel Macs cannot install the local backend: PyTorch publishes no Intel-Mac (macOS x86_64) wheels. " +
        "Connect the app to a VoiceStudio backend on another computer (docs/install/macos.md). " +
        "On an Apple Silicon Mac, run this from a native arm64 terminal with an arm64 Bun or Node.",
    );
  const variant = await selectVariant({ env, platform, arch });
  const windowsRocm = platform === "win32" && variant === "rocm";
  if (windowsRocm && arch !== "x64")
    throw new Error("Windows ROCm requires Windows x64 Python 3.12 (cp312).");
  // Slow or lossy links need a bigger HTTP budget than uv's defaults; CI's
  // smoke matrix uses the same values, so this only changes standalone runs.
  const httpDefaults = {
    ...(env.UV_HTTP_TIMEOUT ? {} : { UV_HTTP_TIMEOUT: "120" }),
    ...(env.UV_HTTP_RETRIES ? {} : { UV_HTTP_RETRIES: "5" }),
  };
  const environment = {
    ...env,
    ...httpDefaults,
    ...(windowsRocm ? { OMNIVOICE_TORCH_VARIANT: "rocm" } : {}),
  };
  // The matched torch stack has no native Windows ARM64 torchaudio wheel.
  const pythonArgs = windowsRocm
    ? ["--python", "cpython-3.12-windows-x86_64"]
    : platform === "win32" && arch === "arm64"
      ? ["--python", "cpython-3.11-windows-x86_64"]
      : [];
  const syncArgs = windowsRocm
    ? windowsRocmSyncArgs(readFileSync(resolve(root, "uv.lock"), "utf8"))
    : torchSyncArgs(variant);
  log(
    `[setup] PyTorch: ${variant}${variant === "cpu" ? " (GPU acceleration unavailable or disabled; inference will be slower)" : ""}`,
  );
  const syncStatus = await uvSyncResilient({
    run,
    env: environment,
    syncArgs: [...syncArgs, ...pythonArgs],
    log,
  });
  if (syncStatus !== 0) return syncStatus;
  await repairNativeLibraries(root, platform, { env: environment });
  for (const args of windowsRocm
    ? [
        ["run", "--no-sync", "python", "scripts/setup.py", "--windows-prerequisites-only"],
        ["run", "--no-sync", "python", "-m", "backend.core.windows_rocm.install", "--uv", "uv"],
      ]
    : []) {
    const result = run("uv", args, { cwd: root, env: environment, stdio: "inherit" });
    if (result.error) throw result.error;
    if (result.status !== 0) return result.status ?? 1;
    if (args.includes("backend.core.windows_rocm.install"))
      await repairNativeLibraries(root, platform, { env: environment });
  }
  const setup = run("uv", ["run", "--no-sync", "python", "scripts/setup.py"], {
    cwd: root,
    env: environment,
    stdio: "inherit",
  });
  if (setup.error) throw setup.error;
  return setup.status ?? 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  setupApi()
    .then((code) => {
      process.exitCode = code;
    })
    .catch((error) => {
      console.error(`[setup] ${error.message}`);
      process.exitCode = 1;
    });
}
