import { test, expect } from "@playwright/test";
import path from "node:path";
import {mkdirSync} from "node:fs";
test("inspect, compare, export, and delete a synthetic dataset", async ({
  page,
}) => {
  mkdirSync("artifacts", {recursive:true});
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  const datasetName = `Retail QA ${Date.now()}`;
  await page.getByLabel("Dataset name").fill(datasetName);
  await page
    .getByLabel("CSV file")
    .setInputFiles(path.resolve("../sample_data/retail_messy.csv"));
  await page.getByRole("button", { name: "Upload & inspect" }).click();
  await expect(page.getByRole("combobox", {name:"Version", exact:true}).locator("option:checked")).toHaveText("v1 · retail_messy.csv · completed", {timeout:30000});
  await expect(
    page.getByRole("heading", { name: "Column profiles" }),
  ).toBeVisible({ timeout: 30000 });
  await page.getByRole("button", { name: "amount", exact: true }).click();
  await expect(page.getByText("COLUMN DETAIL", { exact: true })).toBeVisible();
  await page.screenshot({path:"artifacts/overview.png",fullPage:true});
  await page.getByRole("tab", { name: "Findings", exact: true }).click();
  await expect(
    page.getByText("Some nonmissing values do not parse as numeric."),
  ).toBeVisible();
  await page
    .getByLabel("CSV file")
    .setInputFiles(path.resolve("../sample_data/retail_next.csv"));
  await page.getByRole("button", { name: "Upload & inspect" }).click();
  await expect(page.getByRole("combobox", {name:"Version", exact:true}).locator("option:checked")).toHaveText("v2 · retail_next.csv · completed", {timeout:30000});
  await expect(
    page.getByRole("heading", { name: "Column profiles" }),
  ).toBeVisible({ timeout: 30000 });
  await page.getByRole("tab", { name: "Compare", exact: true }).click();
  await page.getByRole("combobox", { name:"Baseline", exact:true }).selectOption({ index: 1 });
  await page
    .getByRole("combobox", { name:"Candidate", exact:true })
    .selectOption({ index: 2 });
  await page.getByRole("button", { name: "Compare versions" }).click();
  await expect(
    page.getByText("customer_segment", { exact: false }).first(),
  ).toBeVisible({ timeout: 30000 });
  await page.screenshot({path:"artifacts/comparison.png",fullPage:true});
  await page.getByRole("tab", { name: "Report", exact: true }).click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download JSON" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^datalens-.*\.json$/);
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream!) chunks.push(chunk);
  const report = JSON.parse(Buffer.concat(chunks).toString());
  expect(report.summary.rows).toBe(200);
  expect(report.examples_included).toBe(false);
  await expect(page.getByRole("button", {name:"Print / save PDF"})).toBeEnabled();
  await page.emulateMedia({media:"print"});
  await expect(page.getByRole("button", {name:"Upload & inspect"})).not.toBeVisible();
  await page.screenshot({path:"artifacts/print-report.png",fullPage:true});
  await page.emulateMedia({media:"screen"});
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await expect(
    page.getByRole("heading", { name: "Portable report" }),
  ).toBeVisible();
  await page.screenshot({path:"artifacts/mobile-report.png",fullPage:true});
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete dataset" }).click();
  await expect(
    page.getByRole("heading", { name: "Know what’s in your data." }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
