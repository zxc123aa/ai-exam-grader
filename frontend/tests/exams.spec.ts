import { expect, test } from "@playwright/test"

test.use({ storageState: "playwright/.auth/user.json" })

const pngBuffer = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAASwAAAGQCAYAAABkW7XSAAAACXBIWXMAAAsTAAALEwEAmpwYAAAA/ElEQVR4nO3TQQ0AIBDAMMC/5+ECjiYKenb2Z4CkzNsB4G0H8BKgAkAFgAoAFQAqAFQAqABQAVABoAJABYAKABUAKgBUAKgAUAGgAkAFgAoAFQAqAFQAqABQAaACQAWACgAVACoAVACoAFABoAJABYAKABUAKgBUAKgAUAGgAkAFgAoAFQAqAFQAqABQAaACQAWACgAVACoAVACoAFABoAJABYAKABUAKgBUAKgAUAGgAkAFgAoAFQAqAFQAqABQAaACQAWACgAVACoAVACoAFABoAJABYAKABUAKgBUAKgAUAGgAkAFgAoAFQAqAFQAqABQAaACQAWACgAVACoAVACoAFABoAJABYAKABUAKgBUAKgAUAGgAkAFgAoAFQAqAFQAqABQAaACQAWACgAVACoAVACoAFABoAJABYAKABUAKgBUAKgAUAGgAjDuApPjAeeWAAAAAElFTkSuQmCC",
  "base64",
)

test("Exams page is accessible and shows initial copy", async ({ page }) => {
  await page.goto("/exams")
  await expect(
    page.getByRole("heading", { name: "Exams", exact: true }),
  ).toBeVisible()
  await expect(
    page.getByText(
      "Create exams and upload blank paper files for template marking",
    ),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "New Exam" }).first(),
  ).toBeVisible()
  await expect(
    page
      .getByRole("heading", { name: "No exams yet" })
      .or(page.getByRole("columnheader", { name: "Title" })),
  ).toBeVisible()
})

test("Can upload a blank paper and mark a template region", async ({
  page,
}) => {
  const title = `Marking Exam ${Date.now()}`

  await page.goto("/exams")
  await page.getByRole("button", { name: "New Exam" }).first().click()
  await page.getByPlaceholder("English Midterm").fill(title)
  await page.getByRole("button", { name: "Create" }).click()
  await expect(page.getByText("Exam created")).toBeVisible()

  const row = page.getByRole("row").filter({ hasText: title })
  await expect(row).toBeVisible()

  await row.getByRole("button", { name: "Files" }).click()
  await page.getByTestId("exam-file-input").setInputFiles({
    name: "blank.png",
    mimeType: "image/png",
    buffer: pngBuffer,
  })
  await page.getByTestId("exam-file-upload-button").click()
  await expect(page.getByText("Exam file uploaded")).toBeVisible()
  await expect(page.getByText("blank.png")).toBeVisible()
  await page.keyboard.press("Escape")

  await row.getByRole("link", { name: "Mark" }).click()
  await expect(page.getByText("Page 1 of 1")).toBeVisible()

  const canvas = page.getByTestId("region-marking-canvas")
  const box = await canvas.boundingBox()
  expect(box).not.toBeNull()
  if (!box) return

  await page.mouse.move(box.x + box.width * 0.18, box.y + box.height * 0.18)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.58, box.y + box.height * 0.42)
  await page.mouse.up()

  await page.getByPlaceholder("Q1").fill("Q1")
  await page.getByRole("button", { name: "Save Region" }).click()
  await expect(page.getByText("Region saved")).toBeVisible()
  await expect(page.getByTestId("saved-region-Q1")).toBeVisible()

  await page.getByTestId("saved-region-Q1").click()
  await page.getByTestId("selected-region-label-input").fill("Q1 revised")
  await page.getByRole("button", { name: "Save Changes" }).click()
  await expect(page.getByText("Region updated")).toBeVisible()
  await expect(page.getByTestId("saved-region-Q1 revised")).toBeVisible()

  await page.getByTestId("delete-region-Q1 revised").click()
  await expect(page.getByText("Region deleted")).toBeVisible()
  await expect(page.getByTestId("saved-region-Q1 revised")).not.toBeVisible()
})

test("Can upload and preview a student submission", async ({ page }) => {
  const title = `Submission Exam ${Date.now()}`

  await page.goto("/exams")
  await page.getByRole("button", { name: "New Exam" }).first().click()
  await page.getByPlaceholder("English Midterm").fill(title)
  await page.getByRole("button", { name: "Create" }).click()
  await expect(page.getByText("Exam created")).toBeVisible()

  const row = page.getByRole("row").filter({ hasText: title })
  await expect(row).toBeVisible()

  await row.getByRole("button", { name: "Files" }).click()
  await page.getByTestId("exam-file-input").setInputFiles({
    name: "blank.png",
    mimeType: "image/png",
    buffer: pngBuffer,
  })
  await page.getByTestId("exam-file-upload-button").click()
  await expect(page.getByText("Exam file uploaded")).toBeVisible()
  await page.keyboard.press("Escape")

  await row.getByRole("link", { name: "Mark" }).click()
  await expect(page.getByText("Page 1 of 1")).toBeVisible()
  const canvas = page.getByTestId("region-marking-canvas")
  const box = await canvas.boundingBox()
  expect(box).not.toBeNull()
  if (!box) return
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.55, box.y + box.height * 0.4)
  await page.mouse.up()
  await page.getByPlaceholder("Q1").fill("Q1")
  await page.getByRole("button", { name: "Save Region" }).click()
  await expect(page.getByText("Region saved")).toBeVisible()

  await page.goto("/exams")
  const updatedRow = page.getByRole("row").filter({ hasText: title })
  await expect(updatedRow).toBeVisible()

  await updatedRow.getByRole("button", { name: "Submissions" }).click()
  await page.getByTestId("submission-student-name-input").fill("Student A")
  await page.getByTestId("submission-student-identifier-input").fill("A001")
  await page.getByTestId("submission-file-input").setInputFiles({
    name: "student-a.png",
    mimeType: "image/png",
    buffer: pngBuffer,
  })
  await page.getByTestId("submission-upload-button").click()

  await expect(page.getByText("Student submission uploaded")).toBeVisible()
  await expect(page.getByText("Student A", { exact: true })).toBeVisible()
  await expect(page.getByText(/registration pending/i)).toBeVisible()
  await expect(page.getByText(/^pending$/i)).toBeVisible()

  await page.getByRole("button", { name: "Confirm" }).click()
  await expect(page.getByText("Registration status updated")).toBeVisible()
  await expect(page.getByText(/ready for review/i)).toBeVisible()
  await expect(page.getByText(/manual confirmed · 100%/i)).toBeVisible()

  await page.getByRole("button", { name: "Preview" }).click()
  await expect(page.getByText("Page 1 of 1")).toBeVisible()
  await expect(page.getByAltText("student-a.png")).toBeVisible()
  await expect(page.getByTestId("submission-overlay-region-Q1")).toBeVisible()

  await page.getByRole("link", { name: "Review" }).click()
  await expect(page.getByRole("heading", { name: title })).toBeVisible()
  await expect(page.getByTestId("submission-review-canvas")).toBeVisible()
  await expect(page.getByTestId("review-region-list-Q1")).toBeVisible()
  await page.getByTestId("run-submission-processing-button").click()
  await expect(
    page.getByText(/submission processing task started/i),
  ).toBeVisible()
  await expect(page.getByText(/succeeded · 100%/i)).toBeVisible()
  await expect(page.getByTestId("review-region-list-Q1")).toContainText(
    /needs review/i,
  )
  await page.getByTestId("review-score-input").fill("4")
  await page.getByTestId("review-max-score-input").fill("5")
  await page.getByTestId("review-comment-input").fill("Good method")
  await page.getByTestId("review-save-annotation-button").click()
  await expect(page.getByText("Annotation saved")).toBeVisible()
  await expect(page.getByTestId("review-region-list-Q1")).toContainText(
    /needs review/i,
  )
})
