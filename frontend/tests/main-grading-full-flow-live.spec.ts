import path from "node:path"

import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

test("main GUI confirms Gemini OCR before GPT grading", async ({ page }) => {
  test.setTimeout(420_000)
  const apiBase = "http://127.0.0.1:8000/api/v1"
  const login = await page.request.post(`${apiBase}/login/access-token`, {
    form: {
      username: process.env.LIVE_TEST_EMAIL ?? "",
      password: process.env.LIVE_TEST_PASSWORD ?? "",
    },
  })
  expect(login.ok()).toBeTruthy()
  const { access_token: token } = await login.json()
  const headers = { Authorization: `Bearer ${token}` }

  const examsResponse = await page.request.get(`${apiBase}/exams/?limit=100`, {
    headers,
  })
  expect(examsResponse.ok()).toBeTruthy()
  const exam = (await examsResponse.json()).data.find(
    (item: { title: string }) => item.title === "扫描流程验证-物理双页卷",
  )
  expect(exam).toBeTruthy()

  const submissionsResponse = await page.request.get(
    `${apiBase}/exams/${exam.id}/submissions`,
    { headers },
  )
  expect(submissionsResponse.ok()).toBeTruthy()
  const submissions = (await submissionsResponse.json()).data
  expect(submissions[0]?.student_identifier).toBe("E2E-20260715-01")

  const revisionsResponse = await page.request.get(
    `${apiBase}/exams/${exam.id}/standard-answers/revisions`,
    { headers },
  )
  expect(revisionsResponse.ok()).toBeTruthy()
  const publishedRevisions = (await revisionsResponse.json()).data.filter(
    (item: { status: string }) => item.status === "published",
  )
  expect(publishedRevisions.length).toBeGreaterThan(0)

  await page.addInitScript(
    (value) => localStorage.setItem("access_token", value),
    token,
  )
  await page.goto(`/exams/${exam.id}/grading`)
  await expect(page.getByRole("heading", { name: "批量批改" })).toBeVisible()

  const existingRuns = await (
    await page.request.get(`${apiBase}/grading/runs?exam_id=${exam.id}`, {
      headers,
    })
  ).json()
  let recognitionRun = existingRuns.data.find(
    (run: { status: string; config_snapshot?: Record<string, unknown> }) =>
      run.status === "completed" &&
      run.config_snapshot?.pipeline === "recognition_preview" &&
      (
        run.config_snapshot?.timing as
          | { graphicalFallbackCount?: number }
          | undefined
      )?.graphicalFallbackCount,
  )
  if (!recognitionRun) {
    const recognitionResponsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/grading/recognition/runs") &&
        response.request().method() === "POST",
    )
    await page.getByRole("button", { name: "开始 Gemini 识别" }).click()
    recognitionRun = await (await recognitionResponsePromise).json()
    await expect
      .poll(
        async () => {
          const response = await page.request.get(
            `${apiBase}/grading/runs/${recognitionRun.id}`,
            { headers },
          )
          return (await response.json()).status
        },
        { timeout: 180_000 },
      )
      .toBe("completed")
  }

  const recognitionItemsResponse = await page.request.get(
    `${apiBase}/grading/recognition/runs/${recognitionRun.id}/items`,
    { headers },
  )
  expect(recognitionItemsResponse.ok()).toBeTruthy()
  const recognitionItems = await recognitionItemsResponse.json()
  expect(recognitionItems).toHaveLength(publishedRevisions.length)
  expect(
    recognitionItems.every(
      (item: { student_answer?: string }) =>
        (item.student_answer ?? "").trim().length > 0,
    ),
  ).toBeTruthy()
  const graphicalItems = recognitionItems.filter(
    (item: { question_text?: string }) =>
      /作图|画出|示意图|绕法/.test(item.question_text ?? ""),
  )
  expect(graphicalItems.length).toBeGreaterThan(0)
  expect(
    graphicalItems.every(
      (item: { student_answer?: string }) =>
        (item.student_answer ?? "").trim().length > 8,
    ),
  ).toBeTruthy()

  if (recognitionRun.config_snapshot?.recognition_confirmed !== true) {
    await expect(
      page.getByRole("button", { name: "确认识别结果，进入批改" }),
    ).toBeVisible({ timeout: 20_000 })
    await page.getByRole("button", { name: "确认识别结果，进入批改" }).click()
  }
  await expect(page.getByText("确认：已确认")).toBeVisible({ timeout: 20_000 })

  const gradingResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/grading/runs") &&
      !response.url().includes("/recognition/") &&
      response.request().method() === "POST",
  )
  await page.getByRole("button", { name: "开始批量批改" }).click()
  const gradingRun = await (await gradingResponsePromise).json()

  await expect
    .poll(
      async () => {
        const response = await page.request.get(
          `${apiBase}/grading/runs/${gradingRun.id}`,
          { headers },
        )
        return (await response.json()).status
      },
      { timeout: 240_000 },
    )
    .toMatch(/^completed/)

  const completedRun = await (
    await page.request.get(`${apiBase}/grading/runs/${gradingRun.id}`, {
      headers,
    })
  ).json()
  expect(completedRun.failed_count).toBe(0)
  expect(completedRun.total_items).toBe(publishedRevisions.length)
  expect(
    Object.keys(completedRun.config_snapshot.answer_revision_ids),
  ).toHaveLength(publishedRevisions.length)

  const reviewQueue = await (
    await page.request.get(
      `${apiBase}/grading/runs/${gradingRun.id}/review-queue`,
      { headers },
    )
  ).json()
  const audit = await (
    await page.request.get(`${apiBase}/grading/runs/${gradingRun.id}/audit`, {
      headers,
    })
  ).json()
  const totalScore = audit
    .filter((item: { source: string }) => item.source === "auto")
    .reduce(
      (sum: number, item: { new_score: number | null }) =>
        sum + Number(item.new_score ?? 0),
      0,
    )

  await page.reload()
  await expect(page.getByText("最近批次")).toBeVisible()
  await page.screenshot({
    path: path.resolve(process.cwd(), "../outputs/main-grading-full-flow.png"),
    fullPage: true,
  })

  console.log(
    JSON.stringify({
      exam_id: exam.id,
      recognition_run_id: recognitionRun.id,
      grading_run_id: gradingRun.id,
      question_count: completedRun.total_items,
      average_confidence: completedRun.average_confidence,
      review_items: reviewQueue.length,
      total_score: totalScore,
      total_elapsed_ms: completedRun.timing?.total_elapsed_ms ?? null,
    }),
  )
})
