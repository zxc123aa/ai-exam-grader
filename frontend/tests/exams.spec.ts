import { readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { expect, test } from "@playwright/test"

test.use({ storageState: "playwright/.auth/user.json" })

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const scanPhotoBuffer = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAPAAAACMCAIAAADN17N/AAACUUlEQVR4nO3dMW4UMRiAUYI4B4o4zVYUKVCKlBwB5RBRjkBJRcmBoignoUmRkhkNY/vLe/1qXXz6d8drea8utzcfoOLj6AXAkQRNiqBJETQpgiZF0KQImhRBkyJoUgRNiqBJETQpgiZF0Ezqz8+HHa/6dPg6WMu+bqYl6JPEuplWLWjdvHM7g9YNc/JQSIqgT/L89PL89DJ6FX2CJkXQpAiaFEGTImhSBE2KoEkRNPPa8YO0oEkRNCmCJmVP0I7aMS0TmhRBkyJoUgRNiqBJETQpgiZF0KQImhRBkyJoUgRNyrC77b7d/Rj11pv8/vU4eglsYEKTMvj20Znn3yqfIbxlQpMiaFIETYqgSRE0KYImRdCkCJoUQTO1rZfACJoUQZMy+CyH8xIca/OEdrEdMxs2oWc+Z8e6fIcmRdCkCJqUwbsc7LDo1tA5T00mNCkm9KoW2iY68yPFhCZF0KQImhRBkyJoUgRNiqBJETQpgiZF0KQImhRnOVa16Jm7/82EJsWEXs9C5+zOZ0KTImhmt+nmDEGTImhSBE3KtqDdA8bkTGhSBE2KoEkRNCmCJkXQpAiaFEGTImhSBE2KoEkRNCmCJkXQpAiaFEGTImhSBE2KoEkRNCmCJkXQpAiaFEGzgH+/EEbQpAiaFEGTsiFoF9sxPxOaFEGTImhSBE2KoEkRNCmCJkXQpPhr5JNcf/k8egnvgqB59fX7/eglHEDQ52kUM7lU0IphW9CKYXJXl9ub0WuAw9i2I0XQpAiaFEGTImhSBE2KoEkRNCmCJkXQpPwFG643VY7d2z0AAAAASUVORK5CYII=",
  "base64",
)

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
    buffer: scanPhotoBuffer,
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
  await expect(page.getByTestId("annotation-crop-preview")).toBeVisible()
  await expect(page.getByTestId("annotation-ocr-status")).toContainText(
    /not configured/i,
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

test("PaddleOCR draft appears in the review workspace", async ({ page }) => {
  test.skip(
    process.env.E2E_PADDLE_OCR !== "1",
    "Requires local ocr-service and backend OCR_ENGINE=paddle_http",
  )

  const realExamPageBuffer = readFileSync(
    path.join(
      __dirname,
      "../../materials/English/processed/test1/page_1_left.jpg",
    ),
  )
  const title = `Paddle OCR Exam ${Date.now()}`

  await page.goto("/exams")
  await page.getByRole("button", { name: "New Exam" }).first().click()
  await page.getByPlaceholder("English Midterm").fill(title)
  await page.getByRole("button", { name: "Create" }).click()
  await expect(page.getByText("Exam created")).toBeVisible()

  const row = page.getByRole("row").filter({ hasText: title })
  await expect(row).toBeVisible()

  await row.getByRole("button", { name: "Files" }).click()
  await page.getByTestId("exam-file-input").setInputFiles({
    name: "blank-page.jpg",
    mimeType: "image/jpeg",
    buffer: realExamPageBuffer,
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

  await page.mouse.move(box.x + box.width * 0.08, box.y + box.height * 0.04)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.92, box.y + box.height * 0.24)
  await page.mouse.up()
  await page.getByPlaceholder("Q1").fill("Header")
  await page.getByRole("button", { name: "Save Region" }).click()
  await expect(page.getByText("Region saved")).toBeVisible()

  await page.goto("/exams")
  const updatedRow = page.getByRole("row").filter({ hasText: title })
  await expect(updatedRow).toBeVisible()

  await updatedRow.getByRole("button", { name: "Submissions" }).click()
  await page.getByTestId("submission-student-name-input").fill("Student OCR")
  await page.getByTestId("submission-student-identifier-input").fill("OCR001")
  await page.getByTestId("submission-file-input").setInputFiles({
    name: "student-ocr.jpg",
    mimeType: "image/jpeg",
    buffer: realExamPageBuffer,
  })
  await page.getByTestId("submission-upload-button").click()
  await expect(page.getByText("Student submission uploaded")).toBeVisible()

  await page.getByRole("button", { name: "Confirm" }).click()
  await expect(page.getByText("Registration status updated")).toBeVisible()
  await expect(page.getByText(/ready for review/i)).toBeVisible()

  await page.getByRole("link", { name: "Review" }).click()
  await expect(page.getByRole("heading", { name: title })).toBeVisible()
  await expect(page.getByTestId("review-region-list-Header")).toBeVisible()

  await page.getByTestId("run-submission-processing-button").click()
  await expect(
    page.getByText(/submission processing task started/i),
  ).toBeVisible()
  await expect(page.getByText(/succeeded · 100%/i)).toBeVisible({
    timeout: 180_000,
  })
  await expect(page.getByTestId("annotation-crop-preview")).toBeVisible()
  await expect(page.getByTestId("annotation-ocr-status")).toContainText(
    /succeeded/i,
    { timeout: 180_000 },
  )
  await expect(page.getByText(/Engine: paddleocr-gpu-cu130/i)).toBeVisible()
  await expect(page.getByTestId("annotation-ocr-text")).toContainText(
    /英语试题|海南中学|第一次月考/,
  )
})

test("Can convert a scan photo into a student submission", async ({ page }) => {
  const title = `Scan Submission Exam ${Date.now()}`

  await page.goto("/exams")
  await page.getByRole("button", { name: "New Exam" }).first().click()
  await page.getByPlaceholder("English Midterm").fill(title)
  await page.getByRole("button", { name: "Create" }).click()
  await expect(page.getByText("Exam created")).toBeVisible()

  const row = page.getByRole("row").filter({ hasText: title })
  await expect(row).toBeVisible()

  await row.getByRole("button", { name: "Submissions" }).click()
  await page.getByTestId("submission-student-name-input").fill("Student Scan")
  await page.getByTestId("submission-student-identifier-input").fill("SCAN001")
  await page.getByTestId("submission-scan-photo-input").setInputFiles({
    name: "phone.png",
    mimeType: "image/png",
    buffer: scanPhotoBuffer,
  })
  await page.getByTestId("submission-scan-photo-button").click()

  await expect(page.getByText("Scan photo converted")).toBeVisible()
  await expect(page.getByText("Student Scan", { exact: true })).toBeVisible()
  await expect(page.getByText(/phone-preprocessed\.pdf/)).toBeVisible()
  await expect(page.getByText(/registration pending/i)).toBeVisible()
})
