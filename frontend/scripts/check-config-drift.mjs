import fs from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(process.argv[2] ?? path.join(process.cwd(), ".."));
const frontendSrc = path.join(repoRoot, "frontend", "src");

const allowPortLiteralsIn = new Set([
  path.join(frontendSrc, "lib", "constants.ts"),
]);
const canonicalAxiosClient = path.join(frontendSrc, "api", "api.ts");

function walk(dir, out = []) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      // defensive: never scan deps/build outputs even if someone points us wrong
      if (ent.name === "node_modules" || ent.name === "dist") continue;
      walk(p, out);
    } else if (ent.isFile()) {
      if (!/\.(ts|tsx|js|jsx)$/.test(ent.name)) continue;
      out.push(p);
    }
  }
  return out;
}

function fail(msg) {
  console.error(msg);
  process.exitCode = 1;
}

const forbiddenPortRe = /\b(?:localhost|127\.0\.0\.1):(?:8000|8010)\b|:8000\b|:8010\b/g;
const axiosCreateRe = /\baxios\.create\s*\(/g;
const baseUrlKeyRe = /\bbaseURL\s*:/g;

const files = walk(frontendSrc);
for (const file of files) {
  const text = fs.readFileSync(file, "utf8");

  // 1) hardcoded port drift (allow only constants.ts)
  if (!allowPortLiteralsIn.has(file) && forbiddenPortRe.test(text)) {
    fail(`Config drift: hardcoded API port/origin found in ${path.relative(repoRoot, file)}`);
  }

  // 2) duplicate axios clients/baseURL outside canonical api.ts
  if (file !== canonicalAxiosClient) {
    if (axiosCreateRe.test(text) || baseUrlKeyRe.test(text)) {
      fail(`Config drift: axios client/baseURL should live only in src/api/api.ts (found in ${path.relative(repoRoot, file)})`);
    }
  }
}

if (process.exitCode) {
  console.error("\nFix: route all calls through src/api/api.ts + API_BASE_URL; do not hardcode ports.");
} else {
  console.log("OK: config drift checks passed.");
}

