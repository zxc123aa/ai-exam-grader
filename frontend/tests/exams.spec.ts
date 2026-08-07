import { readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { deflateSync } from "node:zlib"
import { expect, type Page, test } from "@playwright/test"

test.use({ storageState: "playwright/.auth/user.json" })

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// 真实试卷照片：内嵌的微型合成图无法通过扫描解码（cv2.imdecode 失败），
// 预处理流水线需要一张可解码的真实照片
const scanPhotoBuffer = readFileSync(
  path.join(
    __dirname,
    "../../materials/English/processed/test1/page_1_left.jpg",
  ),
)

const pngBuffer = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAASwAAAGQCAYAAABkW7XSAAAACXBIWXMAAAsTAAALEwEAmpwYAAAA/ElEQVR4nO3TQQ0AIBDAMMC/5+ECjiYKenb2Z4CkzNsB4G0H8BKgAkAFgAoAFQAqAFQAqABQAVABoAJABYAKABUAKgAUAGgAkAFgAoAFQAqAFQAqABQAaACQAWACgAVACoAFABoAJABYAKABUAKgAUAGgAkAFgAoAFQAqAFQAqABQAaACQAWACgAVACoAFABoAJABYAKABUAKgAUAGgAkAFgAoAFQAqAFQAqABQAaACQAWACgAVACoAFABoAJABYAKABUAKgAUAGgAjDuApPjAeeWAAAAAElFTkSuQmCC",
  "base64",
)

function crc32(buffer: Buffer) {
  let crc = 0xffffffff
  for (const byte of buffer) {
    crc ^= byte
    for (let bit = 0; bit < 8; bit += 1) {
      crc = crc & 1 ? 0xedb88320 ^ (crc >>> 1) : crc >>> 1
    }
  }
  return (crc ^ 0xffffffff) >>> 0
}

function pngChunk(type: string, data: Buffer) {
  const typeBuffer = Buffer.from(type)
  const length = Buffer.alloc(4)
  length.writeUInt32BE(data.length)
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuffer, data])))
  return Buffer.concat([length, typeBuffer, data, crc])
}

function questionLayoutPng() {
  const width = 300
  const height = 420
  const raw = Buffer.alloc((width * 3 + 1) * height, 255)
  for (let y = 0; y < height; y += 1) {
    raw[y * (width * 3 + 1)] = 0
  }
  const setPixel = (x: number, y: number) => {
    if (x < 0 || x >= width || y < 0 || y >= height) return
    const offset = y * (width * 3 + 1) + 1 + x * 3
    raw[offset] = 20
    raw[offset + 1] = 20
    raw[offset + 2] = 20
  }
  const line = (x1: number, y1: number, x2: number, y2: number) => {
    for (let y = y1; y <= y2; y += 1) {
      for (let x = x1; x <= x2; x += 1) setPixel(x, y)
    }
  }
  for (const y of [55, 165, 280]) {
    line(35, y + 19, width - 40, y + 20)
    line(35, y + 45, width - 40, y + 46)
    line(35, y + 19, 36, y + 46)
    line(width - 41, y + 19, width - 40, y + 46)
    line(45, y + 65, width - 50, y + 66)
  }

  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(width, 0)
  ihdr.writeUInt32BE(height, 4)
  ihdr[8] = 8
  ihdr[9] = 2
  return Buffer.concat([
    Buffer.from("89504e470d0a1a0a", "hex"),
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", deflateSync(raw)),
    pngChunk("IEND", Buffer.alloc(0)),
  ])
}

const questionLayoutBuffer = questionLayoutPng()

/** 通过 /exams 页面的「新建考试」对话框创建考试（需要至少一个已存在班级）。 */
async function createExamViaUI(page: Page, title: string) {
  await page.goto("/exams")
  await page.getByRole("button", { name: "新建考试" }).first().click()
  const dialog = page.getByRole("dialog")
  await dialog.getByPlaceholder("八年级期中考试").fill(title)
  await dialog.getByPlaceholder("语文").fill("物理")
  await dialog.getByPlaceholder("八年级", { exact: true }).fill("高一年级")
  await dialog.getByRole("checkbox", { name: "001班" }).check()
  await dialog.getByLabel(/考试时间/).fill("2026-07-23")
  await dialog.getByRole("button", { name: "创建" }).click()
  await expect(page.getByText("考试创建成功")).toBeVisible({ timeout: 15_000 })
  await expect(dialog).not.toBeVisible()
}

/** 从考试列表进入区域校正页，通过「导入试卷」上传一份空白卷。 */
async function uploadBlankPaper(
  page: Page,
  title: string,
  buffer: Buffer,
  name = "blank.png",
) {
  const row = page.getByRole("row").filter({ hasText: title })
  await expect(row).toBeVisible()
  await row.getByRole("link", { name: /继续：|进入批卷/ }).click()

  await page.getByRole("button", { name: "导入试卷" }).click()
  await page.getByTestId("exam-file-input").setInputFiles({
    name,
    mimeType: "image/png",
    buffer,
  })
  await page.getByTestId("exam-file-upload-button").click()
  await expect(page.getByText("试卷导入成功")).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(page.getByText("第 1 / 1 页")).toBeVisible({ timeout: 15_000 })
}

/** 在标注画布上拖出一个区域并以 Q1 保存。 */
async function drawAndSaveRegion(page: Page) {
  const canvas = page.getByTestId("region-marking-canvas")
  const box = await canvas.boundingBox()
  expect(box).not.toBeNull()
  if (!box) return

  await page.mouse.move(box.x + box.width * 0.18, box.y + box.height * 0.18)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.58, box.y + box.height * 0.42)
  await page.mouse.up()

  await page.getByPlaceholder("输入题号，例如 Q1").fill("Q1")
  await page.getByRole("button", { name: "保存区域" }).click()
  await expect(page.getByText("区域已保存")).toBeVisible()
  await expect(page.getByTestId("saved-region-Q1")).toBeVisible()
}

/** 打开考试行的「更多 → 导入中心」，切到学生答卷 tab。 */
async function openSubmissionImport(page: Page, title: string) {
  await page.goto("/exams")
  const row = page.getByRole("row").filter({ hasText: title })
  await expect(row).toBeVisible()
  await row.getByRole("button", { name: "更多" }).click()
  await page.getByRole("menuitem", { name: "导入中心" }).click()
  const dialog = page.getByRole("dialog")
  await dialog.getByRole("tab", { name: "学生答卷（待批改）" }).click()
  return dialog
}

test("Exams page is accessible and shows initial copy", async ({ page }) => {
  await page.goto("/exams")
  await expect(
    page.getByRole("heading", { name: "考试管理", exact: true }).last(),
  ).toBeVisible()
  await expect(
    page.getByText(
      "创建考试，导入一份卷子图片/PDF，然后识别题目内容和准备标准答案",
    ),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "新建考试" }).first(),
  ).toBeVisible()
  await expect(
    page
      .getByRole("heading", { name: "还没有考试" })
      .or(page.getByRole("columnheader", { name: "名称" })),
  ).toBeVisible()
})

test("Can upload a blank paper and mark a template region", async ({
  page,
}) => {
  const title = `Marking Exam ${Date.now()}`

  await createExamViaUI(page, title)
  await uploadBlankPaper(page, title, pngBuffer)

  await drawAndSaveRegion(page)

  await page.getByTestId("saved-region-Q1").click()
  await page.getByTestId("selected-region-label-input").fill("Q1 revised")
  await page.getByRole("button", { name: "保存修改" }).click()
  await expect(page.getByText("区域已更新")).toBeVisible()
  await expect(page.getByTestId("saved-region-Q1 revised")).toBeVisible()

  await page.getByTestId("delete-region-Q1 revised").click()
  await expect(page.getByText("区域已删除")).toBeVisible()
  await expect(page.getByTestId("saved-region-Q1 revised")).not.toBeVisible()
})

test("Standard answer page requires confirmed questions first", async ({
  page,
}) => {
  // 手动编辑标准答案的旧交互已移除：答案只能由 AI 生成或答案文档整理，
  // 且必须先确认题目。这里验证新门槛提示与跳转。
  const apiBase = "http://localhost:8000/api/v1"
  const login = await page.request.post(`${apiBase}/login/access-token`, {
    form: {
      username: process.env.LIVE_TEST_EMAIL ?? "",
      password: process.env.LIVE_TEST_PASSWORD ?? "",
    },
  })
  expect(login.ok()).toBeTruthy()
  const { access_token: token } = await login.json()
  const headers = { Authorization: `Bearer ${token}` }
  const examResponse = await page.request.post(`${apiBase}/exams/`, {
    headers,
    data: {
      title: `Answer Gate Exam ${Date.now()}`,
      subject: "物理",
      org_id: "00000000-0000-0000-0000-000000000001",
    },
  })
  expect(examResponse.ok()).toBeTruthy()
  const exam = await examResponse.json()

  await page.goto(`/exams/${exam.id}/answers`)
  await expect(page.getByText("尚无已确认题目")).toBeVisible()
  await page.getByRole("link", { name: "前往确认题目" }).click()
  await expect(page).toHaveURL(new RegExp(`/exams/${exam.id}/questions`))
})

test("Can load suggested regions and confirm one as a template region", async ({
  page,
}) => {
  const title = `Candidate Regions Exam ${Date.now()}`

  await createExamViaUI(page, title)
  await uploadBlankPaper(page, title, questionLayoutBuffer, "layout.png")

  // 投影分割引擎在本地运行，不依赖外部 AI 提供者
  await page
    .getByRole("combobox")
    .filter({ hasText: "Gemini 版面分析" })
    .click()
  await page.getByRole("option", { name: "投影分割" }).click()

  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/region-candidates") && response.ok(),
  )
  await page.getByRole("button", { name: "检测题目区域" }).click()
  await responsePromise

  await expect(page.getByTestId("candidate-list-Q1")).toBeVisible()
  await expect(page.getByTestId("candidate-region-Q1")).toBeVisible()

  await page.getByTestId("candidate-list-Q1").click()
  await page.getByRole("button", { name: "保存区域" }).click()
  await expect(page.getByText("区域已保存")).toBeVisible()
  await expect(page.getByTestId("saved-region-Q1")).toBeVisible()
})

test("Can upload and preview a student submission", async ({ page }) => {
  test.setTimeout(120_000)
  const title = `Submission Exam ${Date.now()}`

  await createExamViaUI(page, title)
  await uploadBlankPaper(page, title, pngBuffer)
  await drawAndSaveRegion(page)

  const dialog = await openSubmissionImport(page, title)
  await dialog.getByTestId("submission-file-input").setInputFiles({
    name: "student-a.jpg",
    mimeType: "image/jpeg",
    buffer: scanPhotoBuffer,
  })
  await dialog.getByTestId("submission-student-name-input").fill("Student A")
  await dialog.getByTestId("submission-student-identifier-input").fill("A001")
  await dialog.getByTestId("submission-upload-button").click()

  await expect(page.getByText("已上传 1 份学生答卷")).toBeVisible({
    timeout: 90_000,
  })
  await expect(dialog.getByText("Student A", { exact: true })).toBeVisible({
    timeout: 15_000,
  })
  await expect(dialog.getByText("等待配准")).toBeVisible()

  await dialog.getByRole("button", { name: "确认配准" }).click()
  await expect(page.getByText("配准状态已更新")).toBeVisible()
  await expect(dialog.getByText(/人工确认 · 100%/)).toBeVisible()

  await dialog.getByRole("button", { name: "预览" }).click()
  await expect(dialog.getByText("第 1 / 1 页")).toBeVisible()
  await expect(dialog.getByAltText(/student-a/)).toBeVisible({
    timeout: 15_000,
  })
  await expect(dialog.getByTestId("submission-overlay-region-Q1")).toBeVisible()

  await dialog.getByRole("link", { name: "复核" }).click()
  await expect(page.getByTestId("submission-review-canvas")).toBeVisible()
  await expect(page.getByTestId("review-region-list-Q1")).toBeVisible()

  await page.getByTestId("run-submission-processing-button").click()
  await expect(page.getByText("自动处理任务已开始")).toBeVisible()
  await expect(page.getByText(/已完成 · 100%/)).toBeVisible({
    timeout: 60_000,
  })
  await expect(page.getByTestId("review-region-list-Q1")).toContainText(
    "待复核",
  )
  await expect(page.getByTestId("annotation-crop-preview")).toBeVisible()
  await expect(page.getByTestId("annotation-ocr-status")).toContainText(
    /not.configured|未开始/i,
  )

  await page.getByTestId("review-score-input").fill("4")
  await page.getByTestId("review-max-score-input").fill("5")
  await page.getByTestId("review-comment-input").fill("Good method")
  await page.getByTestId("review-save-annotation-button").click()
  await expect(page.getByText("批注已保存")).toBeVisible()
  await expect(page.getByTestId("review-region-list-Q1")).toContainText(
    "待复核",
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

  await createExamViaUI(page, title)
  await uploadBlankPaper(page, title, realExamPageBuffer, "blank-page.jpg")

  const canvas = page.getByTestId("region-marking-canvas")
  const box = await canvas.boundingBox()
  expect(box).not.toBeNull()
  if (!box) return

  await page.mouse.move(box.x + box.width * 0.08, box.y + box.height * 0.04)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.92, box.y + box.height * 0.24)
  await page.mouse.up()
  await page.getByPlaceholder("输入题号，例如 Q1").fill("Header")
  await page.getByRole("button", { name: "保存区域" }).click()
  await expect(page.getByText("区域已保存")).toBeVisible()

  const dialog = await openSubmissionImport(page, title)
  await dialog.getByTestId("submission-file-input").setInputFiles({
    name: "student-ocr.jpg",
    mimeType: "image/jpeg",
    buffer: realExamPageBuffer,
  })
  await dialog.getByTestId("submission-student-name-input").fill("Student OCR")
  await dialog.getByTestId("submission-student-identifier-input").fill("OCR001")
  await dialog.getByTestId("submission-upload-button").click()
  await expect(page.getByText("已上传 1 份学生答卷")).toBeVisible({
    timeout: 90_000,
  })

  await dialog.getByRole("button", { name: "确认配准" }).click()
  await expect(page.getByText("配准状态已更新")).toBeVisible()
  await expect(dialog.getByText(/人工确认/)).toBeVisible()

  await dialog.getByRole("link", { name: "复核" }).click()
  await expect(page.getByTestId("review-region-list-Header")).toBeVisible()

  await page.getByTestId("run-submission-processing-button").click()
  await expect(page.getByText("自动处理任务已开始")).toBeVisible()
  await expect(page.getByText(/已完成 · 100%/)).toBeVisible({
    timeout: 180_000,
  })
  await expect(page.getByTestId("annotation-crop-preview")).toBeVisible()
  await expect(page.getByTestId("annotation-ocr-status")).toContainText(
    "已完成",
    { timeout: 180_000 },
  )
  await expect(page.getByText(/paddleocr-gpu-cu130/i)).toBeVisible()
  await expect(page.getByTestId("annotation-ocr-text")).toContainText(
    /英语试题|海南中学|第一次月考/,
  )
})

test("Can convert a scan photo into a student submission", async ({ page }) => {
  test.setTimeout(120_000)
  const title = `Scan Submission Exam ${Date.now()}`

  await createExamViaUI(page, title)

  const dialog = await openSubmissionImport(page, title)
  await dialog.getByTestId("submission-file-input").setInputFiles({
    name: "phone.jpg",
    mimeType: "image/jpeg",
    buffer: scanPhotoBuffer,
  })
  await dialog.getByTestId("submission-student-name-input").fill("Student Scan")
  await dialog
    .getByTestId("submission-student-identifier-input")
    .fill("SCAN001")
  await dialog.getByTestId("submission-upload-button").click()

  await expect(page.getByText("已上传 1 份学生答卷")).toBeVisible({
    timeout: 90_000,
  })
  await expect(dialog.getByText("Student Scan", { exact: true })).toBeVisible({
    timeout: 15_000,
  })
  await expect(dialog.getByText(/phone-preprocessed\.pdf/)).toBeVisible()
  await expect(dialog.getByText("等待配准")).toBeVisible()
})
