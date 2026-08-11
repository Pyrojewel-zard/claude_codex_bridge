#!/usr/bin/env node
"use strict";

const childProcess = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const https = require("https");
const os = require("os");
const path = require("path");

const root = path.resolve(__dirname, "..");
const manifest = require(path.join(root, "package.json"));
const version = manifest.version;
const vendorRoot = path.join(root, ".ccb-release");
const installLock = path.join(root, ".ccb-install.lock");
const windowsX64ReleaseSurfaceProjectionPath = path.join(
  "lib",
  "terminal_runtime",
  "windows_x64_release_surface_projection.json"
);
const runtimeProbe = [
  "import sys",
  "if sys.version_info < (3, 10):",
  "    raise SystemExit(1)",
  "try:",
  "    import tomllib",
  "except ModuleNotFoundError:",
  "    import tomli",
  "import aiohttp",
  "from cryptography.hazmat.primitives.asymmetric import ed25519, x25519",
  "from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305",
].join("\n");

const releaseSurfaceFailureReasons = new Set([
  "not-windows",
  "not-x64",
  "wow64",
  "python-not-x64",
  "managed-python-missing",
  "managed-python-degraded",
  "helper-missing",
  "helper-not-x64",
  "release-artifact-missing",
  "release-artifact-mismatch",
  "installer-entry-invalid",
  "projection-schema-invalid",
  "baseline-gate-missing",
  "baseline-version-mismatch",
  "upstream-not-admitted",
  "user-surfaces-parity-missing",
  "unknown",
]);

function readWindowsX64ReleaseSurfaceProjection(packageRoot = root) {
  const projectionPath = path.join(packageRoot, windowsX64ReleaseSurfaceProjectionPath);
  const projection = JSON.parse(fs.readFileSync(projectionPath, "utf8"));
  validateWindowsX64ReleaseSurfaceProjection(projection);
  return projection;
}

function validateWindowsX64ReleaseSurfaceProjection(projection) {
  if (!projection || typeof projection !== "object") {
    throw new Error("Windows x64 release-surface projection is not an object");
  }
  if (projection.schema_version !== 1) {
    throw new Error("Unsupported Windows x64 release-surface projection schema_version");
  }
  validateWindowsX64ReleaseHostGate(projection.host_gate);
}

function validateWindowsX64ReleaseHostGate(hostGate) {
  if (!hostGate || typeof hostGate !== "object") {
    throw new Error("Windows x64 release-surface host_gate is missing");
  }
  if (!releaseSurfaceFailureReasons.has(hostGate.default_failure_reason)) {
    throw new Error("Windows x64 release-surface host_gate default_failure_reason is invalid");
  }
  if (!nonEmptyString(hostGate.default_next_action)) {
    throw new Error("Windows x64 release-surface host_gate default_next_action is invalid");
  }
  if (!Array.isArray(hostGate.rules)) {
    throw new Error("Windows x64 release-surface host_gate rules must be an array");
  }
  for (const rule of hostGate.rules) {
    validateWindowsX64ReleaseHostGateRule(rule);
  }
}

function validateWindowsX64ReleaseHostGateRule(rule) {
  if (!rule || typeof rule !== "object") {
    throw new Error("Windows x64 release-surface host_gate rule is not an object");
  }
  for (const field of ["field", "op", "failure_reason", "diagnostic", "next_action"]) {
    if (!nonEmptyString(rule[field])) {
      throw new Error(`Windows x64 release-surface host_gate rule ${field} is invalid`);
    }
  }
  if (!["equals", "in", "not_equals", "is_false", "exists"].includes(rule.op)) {
    throw new Error("Windows x64 release-surface host_gate rule op is invalid");
  }
  if (!releaseSurfaceFailureReasons.has(rule.failure_reason)) {
    throw new Error("Windows x64 release-surface host_gate rule failure_reason is invalid");
  }
  if ((rule.op === "equals" || rule.op === "not_equals") && !Object.prototype.hasOwnProperty.call(rule, "value")) {
    throw new Error("Windows x64 release-surface host_gate comparison rule value is required");
  }
  if (rule.op === "in" && !Array.isArray(rule.value)) {
    throw new Error("Windows x64 release-surface host_gate in rule value must be an array");
  }
}

function collectWindowsX64ReleaseHostEvidence(baseEnv = process.env) {
  return {
    os_platform: process.platform,
    cpu_arch: os.arch(),
    node_arch: process.arch,
    process_arch: process.arch,
    wow64: process.platform === "win32" && baseEnv.PROCESSOR_ARCHITEW6432 ? true : false,
    npm_lifecycle_event: baseEnv.npm_lifecycle_event || null,
    installer_entrypoint: "npm",
  };
}

function evaluateWindowsX64ReleaseHostGate(projection, hostEvidence) {
  const hostGate = projection && projection.host_gate;
  try {
    validateWindowsX64ReleaseHostGate(hostGate);
  } catch (_error) {
    return {
      allowed: false,
      failure_reason: "projection-schema-invalid",
      diagnostic: "Windows x64 release-surface host_gate is invalid.",
      next_action: "Regenerate the Windows x64 release-surface projection.",
    };
  }
  for (const rule of hostGate.rules) {
    if (windowsX64ReleaseHostGateRulePasses(rule, hostEvidence || {})) {
      continue;
    }
    return {
      allowed: false,
      failure_reason: rule.failure_reason,
      diagnostic: rule.diagnostic,
      next_action: rule.next_action,
    };
  }
  return {
    allowed: true,
    failure_reason: null,
    diagnostic: projection.diagnostic || null,
    next_action: projection.next_action || null,
  };
}

function windowsX64ReleaseHostGateRulePasses(rule, hostEvidence) {
  const value = hostEvidence[rule.field];
  if (rule.op === "exists") {
    return valueIsPresent(value);
  }
  if (!valueIsPresent(value)) {
    return false;
  }
  if (rule.op === "is_false") {
    return value === false;
  }
  if (rule.op === "in") {
    return Array.isArray(rule.value) && rule.value.map(normalizeGateValue).includes(normalizeGateValue(value));
  }
  if (rule.op === "equals") {
    return normalizeGateValue(value) === normalizeGateValue(rule.value);
  }
  if (rule.op === "not_equals") {
    return normalizeGateValue(value) !== normalizeGateValue(rule.value);
  }
  return false;
}

function valueIsPresent(value) {
  if (value === null || value === undefined) {
    return false;
  }
  if (typeof value === "string") {
    return value.trim().length > 0;
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  if (typeof value === "object") {
    return Object.keys(value).length > 0;
  }
  return true;
}

function normalizeGateValue(value) {
  return typeof value === "string" ? value.trim().toLowerCase() : value;
}

function nonEmptyString(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function artifactForHost() {
  if (process.platform === "win32") {
    return artifactForWindowsX64ReleaseSurface(root, collectWindowsX64ReleaseHostEvidence());
  }
  if (process.platform === "darwin") {
    return {
      directory: "ccb-macos-universal",
      file: "ccb-macos-universal.tar.gz",
    };
  }
  if (process.platform === "linux" && process.arch === "x64") {
    return {
      directory: "ccb-linux-x86_64",
      file: "ccb-linux-x86_64.tar.gz",
    };
  }
  throw new Error(
    `Unsupported platform for @seemseam/ccb: ${process.platform}/${process.arch}. ` +
      "Use Linux x64, macOS x64, macOS arm64, or install the GitHub release manually."
  );
}

function artifactForWindowsX64ReleaseSurface(packageRoot = root, hostEvidence = collectWindowsX64ReleaseHostEvidence()) {
  const projection = readWindowsX64ReleaseSurfaceProjection(packageRoot);
  const gate = evaluateWindowsX64ReleaseHostGate(projection, hostEvidence);
  if (!gate.allowed) {
    throw new Error(releaseSurfaceDiagnosticMessage(gate.diagnostic, gate.next_action));
  }
  if (!projection.windows_npm_enabled || projection.release_install_entry !== "npm") {
    throw new Error(
      releaseSurfaceDiagnosticMessage(
        projection.diagnostic || "Windows x64 npm release route is diagnostic-only.",
        projection.next_action || "Use install.ps1 for source/dev checkout installs.",
        projection.release_install_entry
      )
    );
  }
  if (!projection.extract_dir || !projection.archive_name) {
    throw new Error(
      releaseSurfaceDiagnosticMessage(
        "Windows x64 release artifact route is missing from the projection.",
        "Regenerate the Windows x64 release-surface projection.",
        projection.release_install_entry
      )
    );
  }
  return {
    directory: projection.extract_dir,
    file: projection.archive_name,
    windows_executable_entry: projection.windows_executable_entry || null,
    windows_bin_entries: projection.windows_bin_entries || {},
  };
}

function releaseSurfaceDiagnosticMessage(diagnostic, nextAction, releaseInstallEntry = null) {
  const detail = releaseInstallEntry ? ` release_install_entry=${releaseInstallEntry}` : "";
  return `${diagnostic}${detail}\nNext action: ${nextAction}`;
}

function installDir(info) {
  if (info && info._base_dir) {
    return path.join(info._base_dir, info.directory);
  }
  return path.join(vendorRoot, info.directory);
}

function executablePath(command = "ccb") {
  const info = artifactForHost();
  const base = installDir(info);
  return executablePathForArtifact(info, command, base);
}

function executablePathForArtifact(info, command = "ccb", base = installDir(info)) {
  if (info && info.windows_bin_entries) {
    const entry = info.windows_bin_entries[command];
    if (!entry) {
      throw new Error(`Windows x64 release projection does not contain Windows executable entry for ${command}`);
    }
    return path.join(base, entry);
  }
  return command === "ccb" ? path.join(base, "ccb") : path.join(base, "bin", command);
}

function runtimePythonPath(info) {
  if (isWindowsReleaseArtifact(info)) {
    return null;
  }
  return path.join(installDir(info), ".venv", "bin", "python");
}

function isReleaseInstalled(info) {
  const dir = installDir(info);
  const versionFile = path.join(dir, "VERSION");
  const ccbPath = executablePathForArtifact(info, "ccb", dir);
  if (!fs.existsSync(versionFile) || !fs.existsSync(ccbPath)) {
    return false;
  }
  try {
    if (!isWindowsReleaseArtifact(info)) {
      fs.accessSync(ccbPath, fs.constants.X_OK);
    }
    return fs.readFileSync(versionFile, "utf8").trim() === version;
  } catch (_error) {
    return false;
  }
}

function isRuntimeReady(info) {
  if (isWindowsReleaseArtifact(info)) {
    return true;
  }
  const pythonPath = runtimePythonPath(info);
  if (!fs.existsSync(pythonPath)) {
    return false;
  }
  const completed = childProcess.spawnSync(pythonPath, ["-c", runtimeProbe], {
    stdio: "ignore",
    timeout: 15000,
  });
  return !completed.error && completed.status === 0;
}

function isWindowsReleaseArtifact(info) {
  return Boolean(info && info.windows_bin_entries);
}

function isInstalled(info) {
  return isReleaseInstalled(info) && isRuntimeReady(info);
}

function download(url, destination, redirects = 0) {
  if (redirects > 5) {
    throw new Error(`Too many redirects while downloading ${url}`);
  }
  return new Promise((resolve, reject) => {
    const request = https.get(url, (response) => {
      const status = response.statusCode || 0;
      if ([301, 302, 303, 307, 308].includes(status) && response.headers.location) {
        response.resume();
        const redirected = new URL(response.headers.location, url).toString();
        download(redirected, destination, redirects + 1).then(resolve, reject);
        return;
      }
      if (status < 200 || status >= 300) {
        response.resume();
        reject(new Error(`Download failed for ${url}: HTTP ${status}`));
        return;
      }
      const file = fs.createWriteStream(destination);
      response.pipe(file);
      file.on("finish", () => file.close(resolve));
      file.on("error", reject);
    });
    request.on("error", reject);
  });
}

function parseSha256Sums(text) {
  const checksums = new Map();
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    const match = trimmed.match(/^([a-fA-F0-9]{64})\s+\*?(.+)$/);
    if (match) {
      checksums.set(path.basename(match[2]), match[1].toLowerCase());
    }
  }
  return checksums;
}

function sha256File(filePath) {
  const hash = crypto.createHash("sha256");
  hash.update(fs.readFileSync(filePath));
  return hash.digest("hex");
}

function run(command, args, options = {}) {
  const completed = childProcess.spawnSync(command, args, {
    stdio: "inherit",
    ...options,
  });
  if (completed.error) {
    throw completed.error;
  }
  if (completed.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed with exit ${completed.status}`);
  }
}

function extractReleaseArchive(info, archivePath) {
  if (isWindowsReleaseArtifact(info) && info.file.endsWith(".zip")) {
    const powershell = process.env.ComSpec ? "powershell" : "pwsh";
    run(powershell, [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-Command",
      "Expand-Archive -LiteralPath $args[0] -DestinationPath $args[1] -Force",
      archivePath,
      vendorRoot,
    ]);
    return;
  }
  run("tar", ["-xzf", archivePath, "-C", vendorRoot]);
}

function bootstrapRuntime(info) {
  const dir = installDir(info);
  const installerPath = path.join(dir, "install.sh");
  if (!isReleaseInstalled(info)) {
    throw new Error(`Cannot bootstrap an incomplete CCB release at ${dir}`);
  }
  if (!fs.existsSync(installerPath)) {
    throw new Error(`CCB runtime bootstrap installer not found at ${installerPath}`);
  }

  const env = {
    ...process.env,
    CODEX_INSTALL_PREFIX: dir,
    CODEX_BIN_DIR: path.join(dir, ".npm-runtime-bin"),
    CCB_SOURCE_KIND: "release",
    CCB_USE_MANAGED_VENV: "1",
    CCB_INSTALL_TOMLI: "1",
    CCB_INSTALL_MOBILE_RELAY_DEPS: "1",
    CCB_INSTALL_ROLES: "0",
    CCB_INSTALL_NEOVIM: "0",
  };
  run("bash", [installerPath, "runtime-bootstrap"], { env });
  if (!isRuntimeReady(info)) {
    throw new Error(`CCB managed Python runtime is not usable at ${runtimePythonPath(info)}`);
  }
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function processIsAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error && error.code === "EPERM";
  }
}

function readLockOwner() {
  try {
    return JSON.parse(fs.readFileSync(path.join(installLock, "owner.json"), "utf8"));
  } catch (_error) {
    return null;
  }
}

function reclaimStaleInstallLock() {
  const owner = readLockOwner();
  if (owner && processIsAlive(Number(owner.pid))) {
    return false;
  }
  try {
    const ageMs = Date.now() - fs.statSync(installLock).mtimeMs;
    if (!owner && ageMs < 30000) {
      return false;
    }
    fs.rmSync(installLock, { recursive: true, force: true });
    return true;
  } catch (_error) {
    return false;
  }
}

async function acquireInstallLock() {
  const configuredTimeout = Number(process.env.CCB_NPM_INSTALL_LOCK_TIMEOUT_MS);
  const timeoutMs =
    Number.isFinite(configuredTimeout) && configuredTimeout > 0
      ? configuredTimeout
      : 15 * 60 * 1000;
  const deadline = Date.now() + timeoutMs;
  const token = crypto.randomBytes(16).toString("hex");

  while (true) {
    try {
      fs.mkdirSync(installLock);
    } catch (error) {
      if (!error || error.code !== "EEXIST") {
        throw error;
      }
      if (reclaimStaleInstallLock()) {
        continue;
      }
      if (Date.now() >= deadline) {
        throw new Error(`Timed out waiting for CCB npm install lock: ${installLock}`);
      }
      await sleep(200);
      continue;
    }

    try {
      fs.writeFileSync(
        path.join(installLock, "owner.json"),
        JSON.stringify({ pid: process.pid, token, createdAt: new Date().toISOString() })
      );
    } catch (error) {
      fs.rmSync(installLock, { recursive: true, force: true });
      throw error;
    }
    return () => {
      const owner = readLockOwner();
      if (owner && owner.token === token) {
        fs.rmSync(installLock, { recursive: true, force: true });
      }
    };
  }
}

async function downloadRelease(info) {
  const baseUrl =
    process.env.CCB_NPM_RELEASE_BASE_URL ||
    `https://github.com/SeemSeam/claude_codex_bridge/releases/download/v${version}`;
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "ccb-npm-"));
  const archivePath = path.join(tmpDir, info.file);
  const sumsPath = path.join(tmpDir, "SHA256SUMS");

  try {
    await download(`${baseUrl}/${info.file}`, archivePath);
    await download(`${baseUrl}/SHA256SUMS`, sumsPath);
    const checksums = parseSha256Sums(fs.readFileSync(sumsPath, "utf8"));
    const expected = checksums.get(info.file);
    if (!expected) {
      throw new Error(`SHA256SUMS does not contain ${info.file}`);
    }
    const actual = sha256File(archivePath);
    if (actual !== expected) {
      throw new Error(`Checksum mismatch for ${info.file}: expected ${expected}, got ${actual}`);
    }

    fs.rmSync(vendorRoot, { recursive: true, force: true });
    fs.mkdirSync(vendorRoot, { recursive: true });
    extractReleaseArchive(info, archivePath);
    if (!fs.existsSync(executablePath("ccb"))) {
      throw new Error(`Installed CCB executable not found at ${executablePath("ccb")}`);
    }
    console.log(`Installed CCB v${version} from ${info.file}.`);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

async function install() {
  const info = artifactForHost();
  if (isInstalled(info)) {
    return;
  }

  const releaseLock = await acquireInstallLock();
  try {
    if (isInstalled(info)) {
      return;
    }
    if (!isReleaseInstalled(info)) {
      if (process.env.CCB_NPM_SKIP_DOWNLOAD === "1") {
        console.warn("Skipping CCB release download because CCB_NPM_SKIP_DOWNLOAD=1.");
        return;
      }
      await downloadRelease(info);
    }
    if (!isRuntimeReady(info)) {
      bootstrapRuntime(info);
    }
  } finally {
    releaseLock();
  }
}

if (require.main === module) {
  install().catch((error) => {
    console.error(error.message || error);
    process.exit(1);
  });
}

module.exports = {
  artifactForWindowsX64ReleaseSurface,
  artifactForHost,
  bootstrapRuntime,
  collectWindowsX64ReleaseHostEvidence,
  evaluateWindowsX64ReleaseHostGate,
  executablePath,
  executablePathForArtifact,
  install,
  installDir,
  isInstalled,
  isReleaseInstalled,
  isRuntimeReady,
  readWindowsX64ReleaseSurfaceProjection,
  runtimePythonPath,
};
