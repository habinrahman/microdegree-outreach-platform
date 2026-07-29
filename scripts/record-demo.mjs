/**
 * Records docs/demo/demo.gif for the operator console README.
 *
 * Prerequisites: Python 3.12+, Node 18+
 * Usage (from repo root): cd scripts && npm install && npx playwright install chromium && npm run record:demo
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import pkg from "gifenc";
const { GIFEncoder, quantize, applyPalette } = pkg;
import pngjs from "pngjs";

const { PNG } = pngjs;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const BACKEND = path.join(ROOT, "backend");
const FRONTEND = path.join(ROOT, "frontend");
const DEMO_DIR = path.join(ROOT, "docs", "demo");
const OUT_GIF = path.join(DEMO_DIR, "demo.gif");
const DEMO_KEY = "demo-readme-recording-key";
const BACKEND_PORT = 8010;
const FRONTEND_PORT = 5173;
const BASE_URL = `http://127.0.0.1:${FRONTEND_PORT}`;

const demoEnv = {
  ...process.env,
  APP_ENV: "dev",
  ADMIN_API_KEY: DEMO_KEY,
  DISABLE_SCHEDULER: "1",
  FOLLOWUPS_DRY_RUN: "true",
  PYTHONUTF8: "1",
  DATABASE_URL: "sqlite:///./readme-demo.db",
};

function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, {
      stdio: "inherit",
      shell: true,
      ...opts,
    });
    child.on("error", reject);
    child.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`${cmd} ${args.join(" ")} exited ${code}`))));
  });
}

function waitForPort(port, timeoutMs = 120_000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(`http://127.0.0.1:${port}`, (res) => {
        res.resume();
        resolve();
      });
      req.on("error", () => {
        if (Date.now() - start > timeoutMs) reject(new Error(`Timed out waiting for :${port}`));
        else setTimeout(tick, 500);
      });
    };
    tick();
  });
}

function startProcess(cmd, args, cwd, env) {
  return spawn(cmd, args, { cwd, env, stdio: "pipe", shell: true });
}

async function capturePng(page) {
  return page.screenshot({ type: "png", fullPage: false });
}

function pngBufferToRgba(buffer) {
  const png = PNG.sync.read(buffer);
  return { width: png.width, height: png.height, data: png.data };
}

function writeGif(frames, width, height) {
  const gif = GIFEncoder();
  for (const frame of frames) {
    const palette = quantize(frame.data, 256);
    const index = applyPalette(frame.data, palette);
    gif.writeFrame(index, width, height, { palette, delay: 950, repeat: 0 });
  }
  gif.finish();
  fs.mkdirSync(path.dirname(OUT_GIF), { recursive: true });
  fs.writeFileSync(OUT_GIF, Buffer.from(gif.bytes()));
}

async function main() {
  fs.mkdirSync(DEMO_DIR, { recursive: true });

  fs.writeFileSync(
    path.join(FRONTEND, ".env.local"),
    `VITE_API_BASE_URL=http://127.0.0.1:${BACKEND_PORT}\nVITE_ADMIN_API_KEY=${DEMO_KEY}\n`,
    "utf8",
  );

  console.log("[DEMO] Installing backend deps (if needed)...");
  await run("python", ["-m", "pip", "install", "-r", "requirements.txt"], { cwd: BACKEND, env: demoEnv });

  console.log("[DEMO] Seeding README demo data (SQLite create_all + seed)...");
  await run("python", ["-m", "app.scripts.seed_readme_demo"], { cwd: BACKEND, env: demoEnv });

  const backend = startProcess(
    "python",
    ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(BACKEND_PORT)],
    BACKEND,
    demoEnv,
  );

  const frontend = startProcess(
    "npm",
    ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(FRONTEND_PORT)],
    FRONTEND,
    { ...process.env, VITE_API_BASE_URL: `http://127.0.0.1:${BACKEND_PORT}`, VITE_ADMIN_API_KEY: DEMO_KEY },
  );

  try {
    await Promise.all([waitForPort(BACKEND_PORT), waitForPort(FRONTEND_PORT)]);

    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const frames = [];

    await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.getByRole("heading", { name: "Performance KPIs" }).waitFor({ timeout: 30_000 });
    await page.waitForTimeout(1200);
    frames.push(await capturePng(page));

    await page.goto(`${BASE_URL}/campaigns`, { waitUntil: "domcontentloaded" });
    await page.getByRole("heading", { name: "Campaigns" }).waitFor({ timeout: 20_000 });
    await page.getByText("Razorpay").first().waitFor({ timeout: 20_000 });
    await page.waitForTimeout(900);
    frames.push(await capturePng(page));

    await page.goto(`${BASE_URL}/replies`, { waitUntil: "domcontentloaded" });
    await page.getByRole("heading", { name: "Replies" }).waitFor({ timeout: 20_000 });
    await page.getByText("Razorpay").first().waitFor({ timeout: 20_000 });
    await page.waitForTimeout(900);
    frames.push(await capturePng(page));

    await page.goto(`${BASE_URL}/outreach`, { waitUntil: "domcontentloaded" });
    await page.getByRole("heading", { name: "Outreach" }).waitFor({ timeout: 20_000 });
    await page.waitForTimeout(1500);
    frames.push(await capturePng(page));

    await browser.close();

    const rgbaFrames = frames.map(pngBufferToRgba);
    writeGif(rgbaFrames, rgbaFrames[0].width, rgbaFrames[0].height);
    console.log(`Wrote ${OUT_GIF} (${frames.length} frames)`);
  } finally {
    backend.kill("SIGTERM");
    frontend.kill("SIGTERM");
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
