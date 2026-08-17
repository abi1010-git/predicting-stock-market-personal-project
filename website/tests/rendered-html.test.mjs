import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html", host: "localhost" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the SignalFive research dashboard", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>SignalFive/);
  assert.match(html, /Can the market.s recent structure inform its next/);
  assert.match(html, /walk-forward/i);
  assert.match(
    html,
    /github\.com\/abi1010-git\/predicting-stock-market-personal-project/,
  );
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape/);
});

test("ships finished content and no starter preview", async () => {
  const [layout, page, dashboard, packageJson, previewFiles] = await Promise.all([
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/Dashboard.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
    import("node:fs/promises").then(({ readdir }) =>
      readdir(new URL("../app/_sites-preview", import.meta.url)),
    ),
  ]);

  assert.match(layout, /SignalFive/);
  assert.match(layout, /og\.png/);
  assert.match(page, /<Dashboard \/>/);
  assert.match(dashboard, /YAHOO FINANCE/);
  assert.match(dashboard, /YAHOO FINANCE/);
  assert.match(dashboard, /RESEARCH, NOT RECOMMENDATION/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  assert.deepEqual(previewFiles, []);
});
