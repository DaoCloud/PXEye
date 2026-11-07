"use strict";
// Render documentation images with the real frontend and local display-only data.
// No NICo, Redfish, SSH or installation backend is started.
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const root = path.resolve(__dirname, "..");
const responses = JSON.parse(
  fs.readFileSync(path.join(root, "examples/ai-factory-view.json"), "utf8"),
);
const output = path.join(root, "docs/assets/screenshots");
const types = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".svg": "image/svg+xml",
};

async function main() {
  fs.mkdirSync(output, { recursive: true });
  const server = http.createServer((req, res) => {
    const requestPath = new URL(req.url, "http://localhost").pathname;
    const file = path.resolve(
      root,
      "src/pxeye/web",
      requestPath === "/" ? "live.html" : "." + requestPath,
    );
    if (
      !file.startsWith(path.join(root, "src/pxeye/web") + path.sep) ||
      !fs.existsSync(file) ||
      !fs.statSync(file).isFile()
    ) {
      res.writeHead(404);
      return res.end();
    }
    res.writeHead(200, {
      "Content-Type": types[path.extname(file)] || "application/octet-stream",
    });
    fs.createReadStream(file).pipe(res);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  let browser;
  try {
    browser = await chromium.launch({
      headless: true,
      ...(process.env.CHROMIUM_EXECUTABLE
        ? { executablePath: process.env.CHROMIUM_EXECUTABLE }
        : {}),
    });
    const origin = `http://127.0.0.1:${server.address().port}`;
    const page = await browser.newPage({
      viewport: { width: 1680, height: 1060 },
      deviceScaleFactor: 1,
      locale: "zh-CN",
      timezoneId: "Asia/Shanghai",
    });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/*", async (route) => {
      const request = route.request(),
        url = new URL(request.url());
      if (url.origin !== origin)
        throw new Error("External request blocked: " + url.origin);
      if (!url.pathname.startsWith("/api/")) return route.continue();
      if (request.method() !== "GET")
        throw new Error("Documentation rendering permits reads only");
      if (!Object.hasOwn(responses, url.pathname))
        throw new Error("Missing view data: " + url.pathname);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(responses[url.pathname]),
      });
    });
    for (const [view, file, selector] of [
      ["topology", "rack-topology.png", ".rack-card"],
      ["tasks", "installation-tasks.png", "[data-task]"],
      ["devices", "device-management.png", 'input[name="eq-device"]'],
    ]) {
      if (view === "topology") await page.goto(origin + "/#" + view);
      else await page.locator('[data-page="' + view + '"]').click();
      try {
        await page.waitForSelector(selector);
      } catch (error) {
        throw new Error(
          error.message +
            "\n" +
            errors.join("\n") +
            "\n" +
            (await page.locator("#main").innerText()),
        );
      }
      if (view === "tasks")
        await page.evaluate(() =>
          readSection("equipment", sectionReads.equipment),
        );
      await page.waitForFunction(
        () =>
          state.resources &&
          state.equipment &&
          !Object.keys(state.readErrors).length,
      );
      if (view === "devices") {
        await page.locator('input[name="eq-device"]').nth(2).check();
        await page.locator('input[name="eq-device"]').nth(3).check();
      }
      await page.evaluate(async () => {
        await document.fonts.ready;
      });
      await page.screenshot({
        path: path.join(output, file),
        fullPage: true,
        animations: "disabled",
      });
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      );
      if (overflow) throw new Error(view + ": horizontal overflow");
      console.log(view + ": " + file);
    }
    if (errors.length) throw new Error(errors.join("\n"));
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
