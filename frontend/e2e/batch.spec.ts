import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

/**
 * Many videos: upload several at once, draw roads on one, copy them to another, leave the
 * third without areas (whole frame), then run all three as a batch, one after another.
 * Junction truth: North Road 2, East Road 3, whole frame 5.
 */
const VIDEO = fileURLToPath(new URL("../../backend/tests/data/videos/synthetic_junction.mp4", import.meta.url));

async function drawRoad(page: Page, [x1, y1, x2, y2]: number[], name: string) {
  const canvas = page.locator("canvas").first();
  let last = "";
  await expect(async () => {
    const b = (await canvas.boundingBox())!;
    const now = `${Math.round(b.width)}x${Math.round(b.height)}`;
    const stable = now === last;
    last = now;
    expect(Math.abs(b.width / b.height - 640 / 360)).toBeLessThan(0.02);
    expect(stable).toBe(true);
  }).toPass({ intervals: [250], timeout: 15_000 });
  const box = (await canvas.boundingBox())!;
  const pt = (x: number, y: number) => [box.x + (x / 640) * box.width, box.y + (y / 360) * box.height] as const;
  await page.getByRole("button", { name: /Draw road/ }).click();
  await page.mouse.move(...pt(x1 + 3, y1 + 3));
  await page.mouse.down();
  await page.mouse.move(...pt(x2 - 3, y2 - 3), { steps: 8 });
  await page.mouse.up();
  await page.getByRole("dialog").getByRole("textbox").fill(name);
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
}

test("uploads several videos and runs them one by one as a batch with separate reports", async ({ page }) => {
  await page.goto("/");
  await page.setInputFiles("input[type=file]", [
    { name: "cam1.mp4", mimeType: "video/mp4", buffer: readFileSync(VIDEO) },
    { name: "cam2.mp4", mimeType: "video/mp4", buffer: readFileSync(VIDEO) },
    { name: "cam3.mp4", mimeType: "video/mp4", buffer: readFileSync(VIDEO) },
  ]);
  await expect(page.getByText("Uploaded 3 of 3")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Whole frame/)).toHaveCount(3);

  // Draw two roads on cam1.
  await page.getByRole("link", { name: "cam1.mp4" }).click();
  await drawRoad(page, [270, 0, 370, 130], "North Road");
  await drawRoad(page, [420, 130, 640, 230], "East Road");
  await expect(page.getByLabel("Region name")).toHaveCount(2);

  // Step to cam2 and copy cam1's roads.
  await page.getByRole("link", { name: "Next →" }).click();
  await expect(page.getByRole("heading", { name: "cam2.mp4" })).toBeVisible();
  await page.getByLabel("Copy areas from video").selectOption({ label: "cam1.mp4 (North Road, East Road)" });
  await page.getByRole("button", { name: "Copy", exact: true }).click();
  await expect(page.getByLabel("Region name")).toHaveCount(2);

  // Select all three and run them as a batch (cam3 has no areas: whole frame).
  await page.getByRole("link", { name: "Videos", exact: true }).click();
  await expect(page.getByText("2 areas")).toHaveCount(2);
  await page.getByRole("button", { name: /Select all/ }).click();
  await page.getByRole("button", { name: /Run 3 selected/ }).click();
  await expect(page.getByRole("heading", { name: "Run 3 videos as a batch" })).toBeVisible();
  await page.getByLabel("Batch name").fill("Junction survey");
  await page.getByRole("radio", { name: /^Fast ~10/ }).check({ force: true });
  await page.locator("select").filter({ has: page.locator("option[value=center]") }).selectOption("center");
  await page.getByText("Advanced settings").click();
  await page.locator("select").filter({ has: page.locator("option[value=motion]") }).selectOption("motion");
  await page.getByRole("button", { name: "Run batch (3 videos)" }).click();

  await page.waitForURL(/\/batches\//);
  await expect(page.getByRole("heading", { name: "Junction survey" })).toBeVisible();
  await expect(page.getByText("3 of 3 videos done")).toBeVisible({ timeout: 150_000 });

  const rows = page.locator("tbody tr");
  await expect(rows).toHaveCount(3);
  for (const i of [0, 1]) {
    await expect(rows.nth(i)).toContainText("North Road 2");
    await expect(rows.nth(i)).toContainText("East Road 3");
  }
  await expect(rows.nth(2)).toContainText("Whole Frame 5");

  // Each video has its own report.
  await rows.nth(1).getByRole("link", { name: "Report" }).click();
  await expect(page.getByRole("link", { name: /Batch \(video 2\)/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator("table").first().getByRole("row", { name: /East Road/ })).toContainText("3");
  await page.getByRole("tab", { name: "Directions" }).click();
  await expect(page.getByRole("heading", { level: 2, name: /North Road/ })).toBeVisible();
  await page.getByRole("tab", { name: "Counted vehicles" }).click();
  await expect(page.getByText("5 area events")).toBeVisible();
  await page.getByLabel("Filter by area or line").selectOption({ label: "East Road" });
  await expect(page.getByText("3 area events")).toBeVisible();

  // Batch downloads: one table for all videos, and a zip with each video's report.
  const batchId = (await page.getByRole("link", { name: /Batch \(video 2\)/ }).getAttribute("href"))!.split("/").pop();
  const zip = await page.request.get(`/api/batches/${batchId}/export?format=zip`);
  expect(zip.ok()).toBeTruthy();
  const csv = await (await page.request.get(`/api/batches/${batchId}/export?format=csv`)).text();
  expect(csv.trim().split("\n")).toHaveLength(1 + 2 + 2 + 1);
});
