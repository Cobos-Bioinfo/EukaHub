// Opens every page of the built app in headless Chrome and fails on a broken one:
// a script error, a failed API request, a missing heading, the wrong view tab, a
// redirect that lands elsewhere, or a page wider than a phone.
//
//   CHROME_PATH=/usr/bin/google-chrome node scripts/smoke.mjs http://localhost:4173
//
// The taxa are in the CI dataset (api/tests/seed.sql) as well as the full one.
import puppeteer from "puppeteer-core";

const base = (process.argv[2] ?? "http://localhost:4173").replace(/\/$/, "");
const chrome = process.env.CHROME_PATH ?? "/usr/bin/google-chrome";

// path, the address it should end on, the view tab it should mark, and whether
// a failed API request is expected (the unknown-taxon page).
const PAGES = [
  { path: "/" },
  { path: "/clade/2759", tab: "Summary" },
  { path: "/clade/40674", tab: "Summary" },
  { path: "/clade/40674/map", tab: "Data map" },
  { path: "/clade/40674/map?view=list", tab: "Data map" },
  { path: "/clade/40674/map?colour=chrom&rank=family&size=assemblies", tab: "Data map" },
  { path: "/clade/40674/records", tab: "Records" },
  { path: "/clade/40674/tree", tab: "Tree of Life" },
  { path: "/clade/40674/gaps", tab: "Gaps" },
  { path: "/clade/9606", tab: "Summary" },
  { path: "/clade/9606/map" },
  { path: "/map/40674?d=9443", lands: "/clade/9443/map", tab: "Data map" },
  { path: "/tree/40674", lands: "/clade/40674/tree", tab: "Tree of Life" },
  { path: "/gaps?root=40674&rank=family", lands: "/clade/40674/gaps?rank=family", tab: "Gaps" },
  { path: "/compare?taxids=40674,9443" },
  { path: "/faq" },
  { path: "/privacy" },
  { path: "/clade/999999999", failing: true },
  { path: "/no-such-page" },
];
const PHONE = ["/", "/clade/40674", "/clade/40674/map", "/clade/40674/map?view=list", "/clade/40674/records", "/clade/9606"];

async function waitForApi() {
  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch(`${base}/api/health`)).ok) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`${base}/api/health did not answer within a minute`);
}

async function check(browser, { path, lands = path, tab, failing = false }, width) {
  const errors = [];
  const page = await browser.newPage();
  await page.setViewport({ width, height: 900 });
  page.on("pageerror", (e) => errors.push(`script error: ${e.message}`));
  // A failed request also logs "Failed to load resource"; the response names it.
  page.on("console", (m) => {
    if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) {
      errors.push(`console: ${m.text()}`);
    }
  });
  page.on("response", (r) => {
    const at = r.url().startsWith(base) ? r.url().slice(base.length) : null;
    if (at === null || r.status() < 400) return;
    if (failing && at.startsWith("/api/")) return;
    errors.push(`${r.status()} from ${at}`);
  });
  await page.goto(base + path, { waitUntil: "networkidle0", timeout: 60000 });
  const seen = await page.evaluate(() => ({
    at: location.pathname + location.search,
    h1: document.querySelector("main h1")?.textContent?.trim() ?? "",
    tab: document.querySelector('.tabs [aria-current="page"]')?.textContent ?? null,
    wide: document.documentElement.scrollWidth > window.innerWidth,
  }));
  if (seen.at !== lands) errors.push(`landed on ${seen.at}, expected ${lands}`);
  if (!seen.h1) errors.push("no heading");
  if (tab !== undefined && seen.tab !== tab) errors.push(`tab ${seen.tab}, expected ${tab}`);
  if (seen.wide) errors.push(`wider than the ${width} px viewport`);
  await page.close();
  return errors.map((e) => `${path} at ${width} px: ${e}`);
}

await waitForApi();
const browser = await puppeteer.launch({ executablePath: chrome, args: ["--no-sandbox"] });
const failures = [];
try {
  for (const p of PAGES) failures.push(...(await check(browser, p, 1280)));
  for (const path of PHONE) failures.push(...(await check(browser, PAGES.find((p) => p.path === path), 390)));
} finally {
  await browser.close();
}
const total = PAGES.length + PHONE.length;
if (failures.length) {
  console.error(failures.join("\n"));
  console.error(`${failures.length} problem(s) on ${total} page loads`);
  process.exit(1);
}
console.log(`${total} page loads, no problems`);
