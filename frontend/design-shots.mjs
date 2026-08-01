// Design review harness: screenshots the pages I need to critique.
// Not part of the app build.
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:5173";
const OUT = "/tmp/shots";
mkdirSync(OUT, { recursive: true });

const shots = [
  { name: "board", path: "/", wait: ".boardrow" },
  { name: "reprice", path: "/brokers/redline/loads/127473232", wait: ".callcard" },
  { name: "cover", path: "/brokers/redline/loads/127472835", wait: ".callcard" },
];

const browser = await chromium.launch();

for (const width of [1280, 420]) {
  const page = await browser.newPage({ viewport: { width, height: 1000 } });
  for (const shot of shots) {
    await page.goto(BASE + shot.path, { waitUntil: "networkidle" });
    await page.waitForSelector(shot.wait, { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT}/${shot.name}-${width}.png`, fullPage: true });
  }
  await page.close();
}

// The sheet, open on each tab that matters.
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
await page.goto(BASE + "/brokers/redline/loads/127472835", { waitUntil: "networkidle" });
await page.waitForSelector(".callcard");
await page.getByRole("button", { name: "Show the work" }).click();
await page.waitForSelector(".sheet");
await page.waitForTimeout(300);
await page.screenshot({ path: `${OUT}/sheet-call.png` });
await page.getByRole("tab", { name: "Ruled out" }).click();
await page.waitForTimeout(200);
await page.screenshot({ path: `${OUT}/sheet-ruledout.png` });
await page.close();

// The dial, dragged off the recommended rate.
const dial = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
await dial.goto(BASE + "/brokers/redline/loads/127472835", { waitUntil: "networkidle" });
await dial.waitForSelector(".dial-input");
for (let i = 0; i < 8; i++) await dial.locator(".dial-input").press("ArrowRight");
await dial.waitForTimeout(250);
await dial.locator(".callcard").screenshot({ path: `${OUT}/dial-moved.png` });
await dial.close();

await browser.close();
console.log("done");
