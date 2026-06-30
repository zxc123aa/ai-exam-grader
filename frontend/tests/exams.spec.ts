import { expect, test } from "@playwright/test"

test.use({ storageState: "playwright/.auth/user.json" })

test("Exams page is accessible and shows initial copy", async ({ page }) => {
  await page.goto("/exams")
  await expect(page.getByRole("heading", { name: "Exams" })).toBeVisible()
  await expect(
    page.getByText(
      "Create exams and upload blank paper files for template marking",
    ),
  ).toBeVisible()
  await expect(page.getByRole("button", { name: "New Exam" })).toBeVisible()
  await expect(
    page.getByRole("heading", { name: "No exams yet" }),
  ).toBeVisible()
  await expect(
    page.getByText("Create the first exam, then upload its blank paper file"),
  ).toBeVisible()
})
