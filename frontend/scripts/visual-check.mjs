import { mkdir } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright-core";

const outputDir = path.resolve(process.cwd(), "../artifacts/visual");
await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({
  executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  headless: true,
});
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const page = await context.newPage();
const consoleErrors = [];
page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });

function shot(name, fullPage = false) {
  return page.screenshot({ path: path.join(outputDir, name), fullPage });
}

async function assertNoPageOverflow(label) {
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    offenders: [...document.querySelectorAll("body *")].filter((element) => {
      const rect = element.getBoundingClientRect();
      return rect.right > window.innerWidth + 1;
    }).slice(0, 8).map((element) => ({ tag: element.tagName, className: element.className, rect: element.getBoundingClientRect().toJSON() })),
    layout: [".app-shell", ".workspace", ".workspace-content", ".page", ".data-table-wrap"].map((selector) => {
      const element = document.querySelector(selector);
      return element ? { selector, rect: element.getBoundingClientRect().toJSON(), clientWidth: element.clientWidth, scrollWidth: element.scrollWidth, overflow: getComputedStyle(element).overflowX } : null;
    }),
  }));
  if (dimensions.document > dimensions.viewport + 1) throw new Error(`${label}: horizontal overflow ${dimensions.document}px > ${dimensions.viewport}px; ${JSON.stringify({ offenders: dimensions.offenders, layout: dimensions.layout })}`);
}

try {
  await page.goto("http://127.0.0.1:8080", { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "登录知识空间" }).waitFor();
  await page.waitForTimeout(350);
  await assertNoPageOverflow("desktop login");
  await shot("12-login-8080-desktop.png");

  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("heading", { name: /需要查找什么/ }).waitFor();
  await page.locator("#workspace-select").waitFor();
  await assertNoPageOverflow("desktop chat");

  await page.getByRole("button", { name: "知识库管理", exact: true }).click();
  await page.getByRole("heading", { name: "知识库管理" }).waitFor();
  await shot("13-knowledge-bases-desktop.png", true);
  await page.getByRole("button", { name: "成员权限", exact: true }).first().click();
  await page.getByRole("heading", { name: /成员权限/ }).waitFor();
  await shot("14-knowledge-base-access-desktop.png");
  await page.getByTitle("关闭", { exact: true }).click();

  await page.getByRole("button", { name: "文档库", exact: true }).click();
  await page.getByRole("heading", { name: "文档库" }).waitFor();
  await shot("15-documents-versions-desktop.png", true);
  await page.getByRole("button", { name: "上传文档", exact: true }).click();
  await page.getByRole("heading", { name: "上传并建立索引" }).waitFor();
  await shot("16-upload-enterprise-desktop.png");
  await page.getByTitle("关闭", { exact: true }).click();

  await page.getByRole("button", { name: "权限与审计", exact: true }).click();
  await page.getByRole("heading", { name: "RAG 与安全参数" }).waitFor();
  await page.getByText("pgvector", { exact: false }).or(page.getByText("sqlite", { exact: false })).first().waitFor();
  await assertNoPageOverflow("desktop governance");
  await shot("17-governance-settings-desktop.png", true);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(200);
  await assertNoPageOverflow("mobile governance");
  await shot("18-governance-settings-mobile.png", true);
  await page.getByTitle("打开导航").click();
  await shot("19-navigation-mobile.png");
  await page.getByRole("button", { name: "知识库管理", exact: true }).click();
  await page.getByRole("heading", { name: "知识库管理" }).waitFor();
  await page.waitForTimeout(300);
  await assertNoPageOverflow("mobile knowledge bases");
  await shot("20-knowledge-bases-mobile.png", true);

  if (consoleErrors.length) throw new Error(`Browser console errors: ${consoleErrors.join(" | ")}`);
  console.log(JSON.stringify({ screenshots: 9, desktop: "1440x900", mobile: "390x844", consoleErrors }, null, 2));
} finally {
  await browser.close();
}
