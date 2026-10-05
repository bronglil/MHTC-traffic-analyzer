import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";

/**
 * Real survey-style footage through the whole system with the real YOLO detector:
 * backend/tests/data/videos/dual_carriageway.mp4 (1366x586) shows three roads; only two
 * are drawn. Hand-counted truth: left carriageway 2 cars (away, N), slip road 1 car
 * (towards, SE); the right main carriageway (not drawn) and horizon traffic must be ignored.
 */
const VIDEO = fileURLToPath(new URL("../../backend/tests/data/videos/dual_carriageway.mp4", import.meta.url));
test.setTimeout(600_000);

async function at(page: Page, x: number, y: number) {
  const box = (await page.locator("canvas").first().boundingBox())!;
  return [box.x + (x / 1366) * box.width, box.y + (y / 586) * box.height] as const;
}

async function nameIt(page: Page, name: string) {
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("textbox").fill(name);
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(dialog).toBeHidden();
}

test("counts only the drawn roads on real footage with YOLO", async ({ page }) => {
  await page.goto("/");
  await page.setInputFiles("input[type=file]", VIDEO);
  await page.waitForURL(/\/videos\//);
  await expect(page.locator("canvas").first()).toBeVisible();
  await page.waitForTimeout(500);

  // Rectangle over the left carriageway.
  await page.getByRole("button", { name: /Draw road/ }).click();
  await page.mouse.move(...(await at(page, 2, 45)));
  await page.mouse.down();
  await page.mouse.move(...(await at(page, 300, 300)), { steps: 5 });
  await page.mouse.move(...(await at(page, 595, 584)), { steps: 5 });
  await page.mouse.up();
  await nameIt(page, "Left carriageway (outbound)");

  // Polygon for the angled slip road beyond the railing.
  await page.getByRole("button", { name: /Draw area/ }).click();
  for (const [x, y] of [[790, 70], [1364, 262], [1364, 428], [840, 150]]) {
    await page.mouse.click(...(await at(page, x, y)));
    await page.waitForTimeout(100);
  }
  await page.keyboard.press("Enter");
  await nameIt(page, "Slip road (inbound)");

  // Default rule: count vehicles crossing each road. The outlines reach the horizon, where cars
  // fade away inside them; covering most of the road still counts as crossing it.
  await expect(page.getByRole("radio", { name: /crosses the area/ })).toBeChecked();
  await page.getByRole("button", { name: "Run analysis" }).click();
  await page.waitForURL(/\/analyses\//);
  await expect(page.getByText("Completed")).toBeVisible({ timeout: 540_000 });

  await page.getByTitle("Show vehicle counts").click();
  const drawer = page.getByRole("complementary", { name: "Vehicle counts" });
  const left = drawer.locator("section").filter({ hasText: "Left carriageway" });
  const slip = drawer.locator("section").filter({ hasText: "Slip road" });
  await expect(drawer.locator("section")).toHaveCount(2);
  await expect(left.locator("span.text-2xl")).toHaveText("2");
  await expect(slip.locator("span.text-2xl")).toHaveText("1");
  await expect(left).toContainText("N 2");   // driving away from the camera
  await expect(slip).toContainText("SE 1");  // towards the camera
});
