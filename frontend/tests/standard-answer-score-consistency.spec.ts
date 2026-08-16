import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

test("standard answer page shows evidence-backed scores totaling 100", async ({
  page,
}) => {
  const examId = "score-exam"
  const expectedScores = [
    3, 3, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 10, 10, 10, 12, 14,
  ]
  const questions = Array.from({ length: 18 }, (_, index) => ({
    id: `question-${index + 1}`,
    exam_id: examId,
    question_key: String(index + 1),
    label: `第${index + 1}题`,
    question_text: `选择题${index + 1}：下列说法正确的是（ ）`,
    question_type:
      index < 8
        ? "single_choice"
        : index < 13
          ? "multiple_choice"
          : index < 15
            ? "experiment"
            : "calculation",
    status: "confirmed",
    recognition_confidence: 0.98,
    region_ids: [],
  }))
  const answerItems = questions.map((question, index) => {
    const score = expectedScores[index]
    const evidence =
      index < 8
        ? "本题共8小题，每小题3分，共24分"
        : index < 13
          ? "本题共5小题，每小题4分，共20分；全部选对得4分，选对但不全得2分，有选错得0分"
          : index < 15
            ? `第${index + 1}题10分`
            : `(${score}分)`
    return {
      id: `answer-item-${index + 1}`,
      question_id: question.id,
      source_question_key: question.question_key,
      answer_text: "B",
      max_score: score,
      rubric_text:
        index >= 8 && index < 13
          ? "全部选对得4分，选对但不全得2分，有选错得0分。"
          : `本题满分${score}分。`,
      scoring_points: [
        {
          id: "p1",
          description: "符合评分要求",
          points: score,
          required: true,
        },
      ],
      confidence: 0.95,
      match_reason: `赋分证据：${evidence}`,
      status: "matched",
      revision_id: null,
      error_message: null,
    }
  })
  const run = {
    id: "answer-run-1",
    source_type: "model",
    provider: "pomoai",
    model: "gpt-5.6-sol",
    document_ids: [],
    status: "completed",
    timing: { modelMs: 1000, totalElapsedMs: 1200 },
    item_count: answerItems.length,
    error_message: null,
    confirmed_at: null,
  }
  let runCreated = false

  await page.route("**/api/v1/users/me", async (route) =>
    route.fulfill({
      json: {
        id: "user-1",
        email: "teacher@example.com",
        full_name: "Teacher",
        is_active: true,
        // 学校角色：平台角色访问 /exams 会被布局重定向到 /platform
        is_superuser: false,
        role: "school_owner",
      },
    }),
  )
  await page.route(`**/api/v1/exams/${examId}`, async (route) =>
    route.fulfill({
      json: { id: examId, title: "赋分一致性验收卷", subject: "物理" },
    }),
  )
  await page.route(`**/api/v1/exams/${examId}/files`, async (route) =>
    route.fulfill({ json: { data: [], count: 0 } }),
  )
  await page.route(`**/api/v1/exams/${examId}/questions`, async (route) =>
    route.fulfill({ json: { data: questions, count: questions.length } }),
  )
  await page.route(
    `**/api/v1/exams/${examId}/answer-preparation-runs`,
    async (route) => {
      const path = new URL(route.request().url()).pathname
      const method = route.request().method()
      if (path.endsWith("/answer-preparation-runs")) {
        if (method === "POST") {
          runCreated = true
          await route.fulfill({ json: run })
        } else {
          await route.fulfill({
            json: runCreated
              ? { data: [run], count: 1 }
              : { data: [], count: 0 },
          })
        }
        return
      }
      if (path.endsWith("/answer-run-1/items")) {
        await route.fulfill({ json: answerItems })
        return
      }
      await route.fulfill({ json: run })
    },
  )
  await page.route(
    `**/api/v1/exams/${examId}/answer-preparation-runs/answer-run-1`,
    async (route) => route.fulfill({ json: run }),
  )
  await page.route(
    `**/api/v1/exams/${examId}/answer-preparation-runs/answer-run-1/items`,
    async (route) => route.fulfill({ json: answerItems }),
  )
  await page.route(
    `**/api/v1/exams/${examId}/standard-answers/revisions`,
    async (route) => route.fulfill({ json: { data: [], count: 0 } }),
  )

  await page.goto("/login")
  await page.evaluate(() => localStorage.setItem("access_token", "mock-token"))
  await page.goto(`/exams/${examId}/answers`)
  await expect(page.getByRole("button", { name: "生成参考答案" })).toBeVisible()

  await page.getByRole("button", { name: "生成参考答案" }).click()
  await expect(page.getByText("答案匹配与评分准则")).toBeVisible()

  // 答案列表默认收起，逐行展开后读取满分输入框
  const displayedScores: number[] = []
  for (let index = 0; index < expectedScores.length; index += 1) {
    const row = page.getByTestId(`answer-item-answer-item-${index + 1}`)
    await row.click()
    const scoreInput = row.locator('input[inputmode="decimal"]')
    await expect(scoreInput).toHaveValue(String(expectedScores[index]))
    displayedScores.push(Number(await scoreInput.inputValue()))
  }
  expect(displayedScores).toEqual(expectedScores)
  expect(displayedScores.reduce((total, score) => total + score, 0)).toBe(100)
  await expect(page.getByText("草稿总分", { exact: true })).toBeVisible()
  await expect(page.getByText("100 分", { exact: true })).toBeVisible()
  await expect(page.getByText(/赋分证据：本题共8小题/).first()).toBeVisible()
  await expect(page.getByText(/选对但不全得2分/).first()).toBeVisible()
  await expect(page.getByText(/赋分证据：第14题10分/).first()).toBeVisible()
  await expect(page.getByText(/赋分证据：\(14分\)/).first()).toBeVisible()
})
