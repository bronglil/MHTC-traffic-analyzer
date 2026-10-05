import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";

/**
 * Full user journey on a 4-road junction where only 2 roads are selected:
 * upload -> drag rectangles over two roads -> name them in the popup ->
 * run -> live view / tiles / counts drawer / exports.
 *
 * Video: backend/tests/data/videos/synthetic_junction.mp4 (640x360). Known truth:
 * North Road is used by 2 vehicles, East Road by 3 (1 bus + 2 cars).
 */
const VIDEO = fileURLToPath(new URL("../../backend/tests/data/videos/synthetic_junction.mp4", import.meta.url));
const ARMS = { North: [270, 0, 370, 130], East: [420, 130, 640, 230] } as const;

async function canvasPoint(page: Page, x: number, y: number) {
  const box = (await page.locator("canvas").first().boundingBox())!;
  return [box.x + (x / 640) * box.width, box.y + (y / 360) * box.height] as const;
}

async function dragRoad(page: Page, [x1, y1, x2, y2]: readonly number[], name: string) {
  await page.getByRole("button", { name: /Draw road/ }).click();
  const a = await canvasPoint(page, x1 + 3, y1 + 3);
  const b = await canvasPoint(page, x2 - 3, y2 - 3);
  await page.mouse.move(...a);
  await page.mouse.down();
  await page.mouse.move((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, { steps: 5 });
  await page.mouse.move(...b, { steps: 5 });
  await page.mouse.up();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("textbox").fill(name);
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toBeHidden();
}

async function uploadJunction(page: Page) {
  await page.goto("/");
  await page.setInputFiles("input[type=file]", VIDEO);
  await page.waitForURL(/\/videos\//);
  await expect(page.locator("canvas").first()).toBeVisible();
  // Wait until the overlay has sized itself to the 16:9 video and stopped resizing (slow machines).
  let last = "";
  await expect(async () => {
    const box = (await page.locator("canvas").first().boundingBox())!;
    const now = `${Math.round(box.width)}x${Math.round(box.height)}`;
    const stable = now === last;
    last = now;
    expect(Math.abs(box.width / box.height - 640 / 360)).toBeLessThan(0.02);
    expect(stable).toBe(true);
  }).toPass({ intervals: [250], timeout: 15_000 });
}

test("counts only the two roads drawn, each under its own name and colour", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (e) => pageErrors.push(e.message));

  await uploadJunction(page);
  const wholeFrame = page.getByRole("checkbox", { name: /Whole Frame/ });
  await expect(wholeFrame).toBeChecked(); // no roads yet -> whole frame is used

  await dragRoad(page, ARMS.North, "North Road");
  await dragRoad(page, ARMS.East, "East Road");

  // Both roads listed with distinct colours; Whole Frame switched off once roads are drawn.
  const names = page.getByLabel("Region name");
  await expect(names).toHaveCount(2);
  await expect(names.nth(0)).toHaveValue("North Road");
  await expect(names.nth(1)).toHaveValue("East Road");
  await expect(wholeFrame).not.toBeChecked();

  // A duplicate name is refused in the popup.
  await page.getByRole("button", { name: /Draw road/ }).click();
  const a = await canvasPoint(page, 10, 140);
  const b = await canvasPoint(page, 200, 220);
  await page.mouse.move(...a);
  await page.mouse.down();
  await page.mouse.move(...b, { steps: 5 });
  await page.mouse.up();
  await page.getByRole("dialog").getByRole("textbox").fill("north road");
  await expect(page.getByRole("dialog").getByText(/already used/)).toBeVisible();
  await expect(page.getByRole("dialog").getByRole("button", { name: "Save" })).toBeDisabled();
  await page.getByRole("dialog").getByRole("button", { name: "Discard" }).click();
  await expect(names).toHaveCount(2);

  // Synthetic overhead clip: motion detector + overhead camera view.
  await page.locator("select").filter({ has: page.locator("option[value=center]") }).selectOption("center");
  await page.getByText("Advanced settings").click();
  await page.locator("select").filter({ has: page.locator("option[value=motion]") }).selectOption("motion");
  await page.getByRole("button", { name: "Run analysis" }).click();
  await page.waitForURL(/\/analyses\//);

  // Live view with the area legend appears while (or right after) processing.
  await expect(page.getByRole("heading", { name: /Live view/ })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("list", { name: "Selected areas" })).toContainText("North Road");

  // Final results: exactly the two selected roads, with the known counts.
  await expect(page.getByText("Completed")).toBeVisible({ timeout: 120_000 });
  const table = page.locator("table").first();
  await expect(table.getByRole("row", { name: /North Road/ })).toContainText("2");
  await expect(table.getByRole("row", { name: /East Road/ })).toContainText("3");
  await expect(table).not.toContainText("Whole Frame");
  await expect(table).not.toContainText("South");

  // Right-edge drawer shows the classified counts per road.
  await page.getByTitle("Show vehicle counts").click();
  const drawer = page.getByRole("complementary", { name: "Vehicle counts" });
  await expect(drawer).toBeInViewport();
  await expect(drawer.getByText("Final results")).toBeVisible();
  const north = drawer.locator("section").filter({ hasText: "North Road" });
  const east = drawer.locator("section").filter({ hasText: "East Road" });
  await expect(north.locator("span.text-2xl")).toHaveText("2");
  await expect(east.locator("span.text-2xl")).toHaveText("3");
  await expect(drawer.locator("section")).toHaveCount(2);
  await page.keyboard.press("Escape");
  await expect(drawer).not.toBeInViewport();

  // Exports contain per-road rows under the user's names.
  const analysisId = page.url().split("/analyses/")[1];
  const csv = await (await page.request.get(`/api/analyses/${analysisId}/export?format=csv`)).text();
  const rows = csv.trim().split("\n").slice(1).map((l) => l.split(",")[1]);
  expect(rows.filter((r) => r === "North Road")).toHaveLength(2);
  expect(rows.filter((r) => r === "East Road")).toHaveLength(3);
  const json = await (await page.request.get(`/api/analyses/${analysisId}/export?format=json`)).json();
  expect(Object.fromEntries(json.summary.areas.map((a: { name: string; total: number }) => [a.name, a.total])))
    .toEqual({ "North Road": 2, "East Road": 3 });
  const xlsx = await page.request.get(`/api/analyses/${analysisId}/export?format=xlsx`);
  expect(xlsx.ok()).toBeTruthy();
  expect((await xlsx.body()).subarray(0, 2).toString()).toBe("PK"); // zip container

  // Region colours stored on the server are distinct and match the drawer swatches.
  const video = await (await page.request.get(`/api/videos/${json.analysis.video_id}`)).json();
  const colors = video.regions.map((r: { color: string }) => r.color);
  expect(new Set(colors).size).toBe(2);
  expect(await north.evaluate((el) => getComputedStyle(el).borderLeftColor)).toBe(hexToRgb(colors[0]));

  expect(pageErrors).toEqual([]);
});

test("polygon drawing works with fast clicks and the drawer is reachable from the video page", async ({ page }) => {
  await uploadJunction(page);
  await page.getByRole("button", { name: /Draw area/ }).click();
  for (const [x, y] of [[275, 5], [365, 5], [365, 125], [275, 125]]) {
    await page.mouse.click(...(await canvasPoint(page, x, y)));
    await page.waitForTimeout(60); // faster than Konva's double-click window
  }
  await page.keyboard.press("Enter");
  await page.getByRole("dialog").getByRole("textbox").fill("North polygon");
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await expect(page.getByLabel("Region name")).toHaveValue("North polygon");

  // Rename inline and confirm it persisted on the server.
  const name = page.getByLabel("Region name");
  await name.fill("North arm");
  await name.press("Enter");
  await expect.poll(async () => {
    const id = page.url().split("/videos/")[1];
    return (await (await page.request.get(`/api/videos/${id}`)).json()).regions[0].name;
  }).toBe("North arm");

  // With the naming popup open, Backspace must not delete the (selected) existing road.
  await page.getByRole("button", { name: /Draw road/ }).click();
  const a = await canvasPoint(page, 430, 140);
  const b = await canvasPoint(page, 620, 220);
  await page.mouse.move(...a);
  await page.mouse.down();
  await page.mouse.move(...b, { steps: 5 });
  await page.mouse.up();
  await page.getByRole("dialog").getByRole("button", { name: "Discard" }).focus();
  await page.keyboard.press("Backspace");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.getByLabel("Region name")).toHaveCount(1);

  // Locked View mode (the default after drawing): a stray drag creates and moves nothing.
  await expect(page.getByRole("button", { name: /View/ })).toHaveAttribute("aria-pressed", "true");
  const videoId = page.url().split("/videos/")[1];
  const before = (await (await page.request.get(`/api/videos/${videoId}`)).json()).regions;
  const s = await canvasPoint(page, 320, 60);      // inside the saved polygon
  const e = await canvasPoint(page, 500, 250);
  await page.mouse.move(...s);
  await page.mouse.down();
  await page.mouse.move(...e, { steps: 6 });
  await page.mouse.up();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const after = (await (await page.request.get(`/api/videos/${videoId}`)).json()).regions;
  expect(after).toEqual(before);

  // No analysis yet -> no drawer tab on the video page.
  await expect(page.getByTitle("Show vehicle counts")).toHaveCount(0);
});

function hexToRgb(hex: string) {
  const n = parseInt(hex.slice(1), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}

