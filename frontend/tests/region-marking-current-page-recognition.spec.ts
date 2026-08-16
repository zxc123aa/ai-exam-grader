import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

const imageBuffer = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAASwAAAGQCAIAAACpW80mAAABKElEQVR4nO3BMQEAAADCoPVPbQwfoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA4G8B5gABnLwV8QAAAABJRU5ErkJggg==",
  "base64",
)

test("marking page exposes current-page recognition and clear controls", async ({
  page,
}) => {
  const recognizedPages: number[] = []
  let fullPaperRecognitionCalled = false

  await page.route("**/api/v1/users/me", async (route) => {
    await route.fulfill({
      json: {
        id: "user-1",
        email: "teacher@example.com",
        full_name: "Teacher",
        is_active: true,
        // 学校角色：平台角色访问 /exams 会被布局重定向到 /platform
        is_superuser: false,
        role: "school_owner",
      },
    })
  })
  await page.route("**/api/v1/exams/exam-1", async (route) => {
    await route.fulfill({
      json: {
        id: "exam-1",
        owner_id: "user-1",
        title: "扫描流程验证-物理双页卷",
        subject: "物理",
        status: "draft",
      },
    })
  })
  await page.route("**/api/v1/exams/exam-1/files", async (route) => {
    await route.fulfill({
      json: {
        data: [
          {
            id: "document-1",
            exam_id: "exam-1",
            document_type: "blank_exam",
            sort_order: 1,
            stored_file_id: "file-1",
            stored_file: {
              id: "file-1",
              uploaded_by_id: "user-1",
              original_filename: "0_0-scanned.pdf",
              content_type: "application/pdf",
              storage_key: "mock.pdf",
              size_bytes: 100,
              sha256:
                "0000000000000000000000000000000000000000000000000000000000000000",
            },
            page_count: 8,
            preprocessing_status: "completed",
            preprocessing_quality: 0.91,
            preprocessing_metadata: {
              source: "manual_quad_document_preprocessing_v1",
              pages: [{ pageNumber: 1 }],
            },
          },
        ],
        count: 1,
      },
    })
  })
  await page.route("**/api/v1/exams/exam-1/regions", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  let candidateDetectionCount = 0
  await page.route(
    "**/api/v1/exams/exam-1/files/document-1/region-candidates**",
    async (route) => {
      candidateDetectionCount += 1
      await new Promise((resolve) => setTimeout(resolve, 150))
      await route.fulfill({
        json: {
          data:
            candidateDetectionCount === 1
              ? [
                  {
                    label: "1",
                    region_type: "question",
                    page_number: 1,
                    x: 0.02,
                    y: 0.02,
                    width: 0.96,
                    height: 0.9,
                    confidence: 0.75,
                    source: "gemini_layout_v1",
                    reasons: [],
                  },
                ]
              : [
                  {
                    label: "1",
                    region_type: "question",
                    page_number: 1,
                    x: 0.1,
                    y: 0.1,
                    width: 0.8,
                    height: 0.2,
                    confidence: 0.9,
                    source: "gemini_layout_v1",
                    reasons: [],
                  },
                  {
                    label: "2",
                    region_type: "question",
                    page_number: 1,
                    x: 0.1,
                    y: 0.32,
                    width: 0.8,
                    height: 0.2,
                    confidence: 0.9,
                    source: "gemini_layout_v1",
                    reasons: [],
                  },
                ],
          count: candidateDetectionCount === 1 ? 1 : 2,
          page_number: 1,
          engine: "gemini_layout_v1",
          elapsed_ms: 10,
        },
      })
    },
  )
  await page.route(
    "**/api/v1/exams/exam-1/files/document-1/pages/*/image**",
    async (route) => {
      await route.fulfill({
        contentType: "image/png",
        body: imageBuffer,
      })
    },
  )
  await page.route(
    "**/api/v1/exams/exam-1/files/document-1/pages/1/reference-recognition",
    async (route) => {
      recognizedPages.push(1)
      await new Promise((resolve) => setTimeout(resolve, 150))
      await route.fulfill({
        json: {
          requestedPageId: "document-1:page:1",
          contextPageIds: ["document-1:page:1", "document-1:page:2"],
          updatedPageIds: ["document-1:page:1"],
          blocks: [
            {
              id: "document-1:page:1::q3a",
              pageId: "document-1:page:1",
              questionNumber: "3",
              label: "第3题前半部分",
            },
          ],
          results: [
            {
              id: "document-1:page:1::q3a",
              blockId: "document-1:page:1::q3a",
              sourceBlockIds: ["document-1:page:1::q3a"],
              questionNumber: "3",
              question: "第3题前半部分",
              studentAnswer: "B",
              confidence: 0.98,
              elapsedMs: 123,
            },
          ],
          timing: {
            orientationMs: 0,
            layoutMs: 10,
            refinementMs: 0,
            cropMs: 5,
            ocrMs: 123,
            totalElapsedMs: 138,
          },
        },
      })
    },
  )
  await page.route(
    "**/api/v1/exams/exam-1/files/document-1/pages/2/reference-recognition",
    async (route) => {
      recognizedPages.push(2)
      await route.fulfill({
        json: {
          requestedPageId: "document-1:page:2",
          contextPageIds: ["document-1:page:1", "document-1:page:2"],
          updatedPageIds: ["document-1:page:2"],
          blocks: [
            {
              id: "document-1:page:1::q3a",
              pageId: "document-1:page:1",
              questionNumber: "3",
              label: "第3题前半部分",
            },
            {
              id: "document-1:page:2::q3b",
              pageId: "document-1:page:2",
              questionNumber: "3",
              label: "第3题续页",
            },
            {
              id: "document-1:page:2::q4",
              pageId: "document-1:page:2",
              questionNumber: "4",
              label: "第4题",
            },
          ],
          results: [
            {
              id: "document-1:page:1::q3a",
              blockId: "document-1:page:1::q3a",
              sourceBlockIds: [
                "document-1:page:1::q3a",
                "document-1:page:2::q3b",
              ],
              questionNumber: "3",
              question: "第3题完整题干（跨页合并）",
              studentAnswer: "B",
              confidence: 0.96,
              elapsedMs: 180,
            },
            {
              id: "document-1:page:2::q4",
              blockId: "document-1:page:2::q4",
              sourceBlockIds: ["document-1:page:2::q4"],
              questionNumber: "4",
              question: "第4题题干",
              studentAnswer: "C",
              confidence: 0.97,
              elapsedMs: 110,
            },
          ],
          timing: {
            orientationMs: 0,
            layoutMs: 9,
            refinementMs: 0,
            cropMs: 4,
            ocrMs: 110,
            totalElapsedMs: 123,
          },
        },
      })
    },
  )
  await page.route(
    "**/api/v1/exams/exam-1/files/reference-recognition",
    async (route) => {
      fullPaperRecognitionCalled = true
      const blocks = Array.from({ length: 8 }, (_, index) => ({
        id: `document-1:page:${index + 1}::q${index + 1}`,
        pageId: `document-1:page:${index + 1}`,
        label: `第${index + 1}题`,
        questionNumber: String(index + 1),
        xmin: 100,
        ymin: 100,
        xmax: 900,
        ymax: 900,
      }))
      await route.fulfill({
        json: {
          blocks,
          results: blocks.map((block, index) => ({
            id: block.id,
            blockId: block.id,
            sourceBlockIds: [block.id],
            questionNumber: String(index + 1),
            question: `全卷第${index + 1}题`,
            studentAnswer: "B",
            confidence: 0.95,
          })),
          timing: { totalElapsedMs: 1000 },
        },
      })
    },
  )
  let importedPayload: Record<string, unknown> | null = null
  await page.route(
    "**/api/v1/exams/exam-1/question-recognition-runs/from-marking",
    async (route) => {
      importedPayload = route.request().postDataJSON()
      await route.fulfill({ json: { id: "marking-run-1" } })
    },
  )
  const markingRun = {
    id: "marking-run-1",
    status: "completed",
    engine: "reference-node-marking-import",
    provider: "marking-result",
    model: "reused",
    document_ids: ["document-1"],
    timing: { totalElapsedMs: 1000 },
    item_count: 1,
    error_message: null,
    confirmed_at: null as string | null,
  }
  await page.route(
    "**/api/v1/exams/exam-1/question-recognition-runs**",
    async (route) => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith("/question-recognition-runs/from-marking")) {
        importedPayload = route.request().postDataJSON()
        return route.fulfill({ json: { id: "marking-run-1" } })
      }
      if (path.endsWith("/question-recognition-runs")) {
        return route.fulfill({ json: { data: [markingRun], count: 1 } })
      }
      if (path.endsWith("/marking-run-1/items")) {
        return route.fulfill({
          json: [
            {
              id: "recognition-item-1",
              run_id: "marking-run-1",
              question_key: "1",
              label: "第1题",
              question_text: "全卷第1题",
              student_answer_text: "B",
              question_type: "single_choice",
              confidence: 0.95,
              notes: null,
              region_ids: [],
              region_snapshots: [{ page_number: 1 }],
              status: "draft",
            },
          ],
        })
      }
      if (path.endsWith("/marking-run-1/confirm")) {
        markingRun.confirmed_at = new Date().toISOString()
        return route.fulfill({ json: markingRun })
      }
      return route.fulfill({ json: markingRun })
    },
  )
  await page.route("**/api/v1/exams/exam-1/questions", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto("/login")
  await page.evaluate(() => localStorage.setItem("access_token", "mock-token"))
  await page.goto("/exams/exam-1/marking")

  const canvas = page.getByTestId("region-marking-canvas")
  const currentPagePanel = page.getByTestId("current-page-recognition-panel")
  const canvasBox = await canvas.boundingBox()
  const panelBox = await currentPagePanel.boundingBox()
  expect(canvasBox?.width).toBeGreaterThan(panelBox?.width ?? 0)
  expect(canvasBox?.width).toBeGreaterThan(600)

  await expect(page.getByRole("button", { name: "识别当前页" })).toBeVisible()
  await expect(page.getByRole("button", { name: "识别全卷" })).toBeVisible()
  await expect(
    currentPagePanel.getByRole("button", { name: "清除本页", exact: true }),
  ).toBeDisabled()
  // 「清除全部识别」收进了「清除」下拉菜单
  await page.getByRole("button", { name: "清除", exact: true }).click()
  await expect(
    page.getByRole("menuitem", { name: "清除全部识别" }),
  ).toBeDisabled()
  await page.keyboard.press("Escape")

  const detectRegionsButton = page.getByRole("button", {
    name: /检测题目区域|检测中/,
  })
  const recognizeCurrentPageButton = page.getByRole("button", {
    name: "识别当前页",
  })
  const recognizeFullPaperButton = page.getByRole("button", {
    name: "识别全卷",
  })

  await detectRegionsButton.click()
  await expect(recognizeCurrentPageButton).toBeDisabled()
  await expect(recognizeFullPaperButton).toBeDisabled()
  await page.getByTestId("candidate-list-1").click()
  await expect(page.getByText("蓝色框是待保存的手动草稿")).toBeVisible()
  await detectRegionsButton.click()
  await expect(page.getByText("蓝色框是待保存的手动草稿")).not.toBeVisible()
  await expect(page.getByTestId("candidate-list-1")).toBeVisible()
  await expect(page.getByTestId("candidate-list-2")).toBeVisible()

  await recognizeCurrentPageButton.click()
  await expect(detectRegionsButton).toBeDisabled()
  await expect(recognizeFullPaperButton).toBeDisabled()

  await expect(
    page.getByRole("heading", { name: "当前页题目与答案" }),
  ).toBeVisible()
  await expect(currentPagePanel).toContainText("第 1 页 · 本页 1 题")
  await expect(currentPagePanel).toContainText("全卷已汇总 1 题")
  await expect(page.getByText("第3题前半部分")).toBeVisible()
  await expect(page.getByText("B", { exact: true })).toBeVisible()
  await expect(
    currentPagePanel.getByRole("button", { name: "清除本页", exact: true }),
  ).toBeEnabled()

  await page.getByRole("button", { name: "下一页" }).click()
  await expect(page.getByText("第 2 / 8 页")).toBeVisible()
  await expect(currentPagePanel).toContainText("本页还没有识别结果")
  await expect(currentPagePanel).not.toContainText("第3题前半部分")
  await page.getByRole("button", { name: "识别当前页" }).click()

  await expect(currentPagePanel).toContainText("第 2 页 · 本页 2 题")
  await expect(currentPagePanel).toContainText("全卷已汇总 2 题")
  await expect(page.getByText("第3题前半部分")).not.toBeVisible()
  await expect(page.getByText("第3题完整题干（跨页合并）")).toBeVisible()
  await expect(page.getByText("第4题题干")).toBeVisible()
  await expect(page.getByText("B", { exact: true })).toBeVisible()
  await expect(page.getByText("C", { exact: true })).toBeVisible()

  await currentPagePanel
    .getByRole("button", { name: "清除本页", exact: true })
    .click()
  await expect(currentPagePanel).toContainText("第 2 页 · 本页 1 题")
  await expect(currentPagePanel).toContainText("第3题完整题干（跨页合并）")
  await expect(page.getByText("第4题题干")).not.toBeVisible()
  expect(recognizedPages).toEqual([1, 2])
  expect(fullPaperRecognitionCalled).toBe(false)

  await page.getByRole("button", { name: "识别全卷" }).click()
  await expect(currentPagePanel).toContainText("已识别 8 / 8 页")
  const continueButton = page.getByRole("button", {
    name: "确认题目并制作标准答案",
  })
  await expect(continueButton).toBeEnabled()
  await continueButton.click()
  await expect(page).toHaveURL(
    /\/exams\/exam-1\/questions\?runId=marking-run-1/,
  )
  expect(importedPayload).toMatchObject({
    document_ids: ["document-1"],
    covered_page_ids: Array.from(
      { length: 8 },
      (_, index) => `document-1:page:${index + 1}`,
    ),
  })
  await expect(
    page.getByTestId("recognition-item-recognition-item-1"),
  ).toBeVisible()
  await page.getByRole("button", { name: "确认题目并进入标准答案" }).click()
  await expect(page).toHaveURL(/\/exams\/exam-1\/answers$/)
})
