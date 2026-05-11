import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const [, , inputPath, outputPath] = process.argv;

if (!inputPath || !outputPath) {
  console.error("Usage: node scripts/run_validation_playwright.mjs <input.json> <output.json>");
  process.exit(1);
}

const input = JSON.parse(await fs.readFile(inputPath, "utf8"));
const outputDir = input.output_dir || path.dirname(outputPath);
await fs.mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 2200 } });

const cases = [];

for (const item of input.cases || []) {
  const page = await context.newPage();
  const consoleMessages = [];
  page.on("console", (message) => {
    consoleMessages.push(`${message.type()}: ${message.text()}`);
  });
  let screenshotPath = "";
  let consoleLogPath = "";
  const domSnapshot = {};
  try {
    await page.goto(item.profile_url, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForTimeout(800);

    const textOf = async (testId) => {
      const locator = page.locator(`[data-testid="${testId}"]`).first();
      if ((await locator.count()) === 0) return "";
      return (await locator.textContent())?.trim() || "";
    };

    domSnapshot.top_summary_diagnosis = await textOf("top-summary-diagnosis");
    domSnapshot.top_summary_stage = await textOf("top-summary-stage");
    domSnapshot.effective_state_raw = await textOf("effective-state-raw");
    domSnapshot.effective_track_raw = await textOf("effective-track-raw");
    domSnapshot.transition_policy = await textOf("transition-policy");
    domSnapshot.schedule_state_raw = await textOf("schedule-state-raw");
    domSnapshot.schedule_track_raw = await textOf("schedule-track-raw");
    domSnapshot.next_best_action = await textOf("next-best-action");
    domSnapshot.intent_headline = await textOf("intent-headline");
    domSnapshot.blocking_inputs = await textOf("blocking-inputs");
    domSnapshot.active_alerts = await textOf("active-alerts");
    domSnapshot.schedule_primary_intent = await textOf("schedule-primary-intent");
    domSnapshot.action_schedule_consistency = await textOf("action-schedule-consistency");
    domSnapshot.transition_card_present = (await page.locator('[data-testid="transition-card"]').count()) > 0;

    const safeKey = String(item.case_key || "case").replace(/[^a-zA-Z0-9_-]+/g, "_");
    screenshotPath = path.join(outputDir, `${safeKey}.png`);
    consoleLogPath = path.join(outputDir, `${safeKey}.console.log`);
    await page.screenshot({ path: screenshotPath, fullPage: true });
    await fs.writeFile(consoleLogPath, consoleMessages.join("\n"), "utf8");
  } catch (error) {
    consoleMessages.push(`error: ${error instanceof Error ? error.message : String(error)}`);
    const safeKey = String(item.case_key || "case").replace(/[^a-zA-Z0-9_-]+/g, "_");
    consoleLogPath = path.join(outputDir, `${safeKey}.console.log`);
    await fs.writeFile(consoleLogPath, consoleMessages.join("\n"), "utf8");
  } finally {
    await page.close();
  }

  cases.push({
    case_key: item.case_key,
    profile_url: item.profile_url,
    screenshot_path: screenshotPath,
    console_log_path: consoleLogPath,
    console_messages: consoleMessages,
    dom_snapshot: domSnapshot,
  });
}

await browser.close();
await fs.writeFile(outputPath, JSON.stringify({ cases }, null, 2), "utf8");
