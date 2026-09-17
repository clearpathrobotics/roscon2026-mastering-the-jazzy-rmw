// One browser for the whole run. Node's test runner spawns a process per file, so without
// this each of the sixteen files would launch and tear down its own Chromium.
import { launchBrowser } from './harness.mjs';

let browser;

export async function globalSetup() {
  browser = await launchBrowser();
  process.env.WEBSHARK_BROWSER_WS = browser.wsEndpoint();
}

export async function globalTeardown() {
  await browser?.close();
}
