import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

test("real question-recognition draft renders backend counts and timing dynamically", async ({
  page,
}) => {
  test.setTimeout(60_000)
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
  const examsResponse = await page.request.get(`${apiBase}/exams/`, { headers })
  expect(examsResponse.ok()).toBeTruthy()
  const exam = (await examsResponse.json()).data.find(
    (item: { title: string }) => item.title === "高一年级物理期中检测题",
  )
  expect(exam).toBeTruthy()
  const runsResponse = await page.request.get(
    `${apiBase}/exams/${exam.id}/question-recognition-runs`,
    { headers },
  )
  expect(runsResponse.ok()).toBeTruthy()
  const run = (await runsResponse.json()).data[0]
  expect(run).toBeTruthy()
  const itemsResponse = await page.request.get(
    `${apiBase}/exams/${exam.id}/question-recognition-runs/${run.id}/items`,
    { headers },
  )
  expect(itemsResponse.ok()).toBeTruthy()
  const items = await itemsResponse.json()
  expect(items.length).toBeGreaterThan(0)
  const confidences = items
    .map((item: { confidence: number | null }) => item.confidence)
    .filter((value: number | null): value is number => value !== null)
  const expectedAverage = Math.round(
    (confidences.reduce((sum: number, value: number) => sum + value, 0) /
      confidences.length) *
      100,
  )

  await page.goto("/login")
  await page.evaluate(
    (value) => localStorage.setItem("access_token", value),
    token,
  )
  await page.goto(`/exams/${exam.id}/questions`)
  await expect(page.getByRole("heading", { name: exam.title })).toBeVisible()
  await expect(page.getByTestId(/^recognition-item-/)).toHaveCount(items.length)
  await expect(page.getByTestId("average-confidence")).toHaveText(
    `${expectedAverage}%`,
  )
  // 耗时明细默认折叠在「批次详情（调试）」里，先展开再断言
  await page.getByText("批次详情（调试）").click()
  await expect(page.getByText("方向检测")).toBeVisible()
  await expect(page.getByText("版面分割")).toBeVisible()
  await expect(page.getByText("裁切", { exact: true })).toBeVisible()
  await expect(page.getByText("OCR", { exact: true })).toBeVisible()
  // 题目列表默认收起，先展开第一行再断言卷面作答
  await page
    .getByTestId(/^recognition-item-/)
    .first()
    .click()
  await expect(
    page.getByText(items[0].student_answer_text, { exact: true }).first(),
  ).toBeVisible()
  await page.screenshot({
    path: "/tmp/real-question-recognition.png",
    fullPage: true,
  })
})

test("question confirmation and immutable answer publishing render end to end", async ({
  page,
}) => {
  test.setTimeout(120_000)
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
      title: `工作流验收-${Date.now()}`,
      subject: "物理",
      // 平台账号创建考试必须指定 org_id（默认学校）
      org_id: "00000000-0000-0000-0000-000000000001",
    },
  })
  expect(examResponse.ok()).toBeTruthy()
  const exam = await examResponse.json()
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z1ZkAAAAASUVORK5CYII=",
    "base64",
  )
  const fileResponse = await page.request.post(
    `${apiBase}/exams/${exam.id}/files`,
    {
      headers,
      multipart: {
        file: {
          name: "workflow-paper.png",
          mimeType: "image/png",
          buffer: png,
        },
        document_type: "blank_exam",
      },
    },
  )
  expect(fileResponse.ok()).toBeTruthy()
  const document = await fileResponse.json()

  const questionItems = [
    {
      id: "10000000-0000-4000-8000-000000000001",
      run_id: "20000000-0000-4000-8000-000000000001",
      source_item_key: "block-1",
      question_key: "1",
      label: "第1题",
      question_text: "质量为 2 kg 的物体受到 4 N 合力，求加速度。",
      student_answer_text: "2 m/s²",
      question_type: "calculation",
      confidence: 0.92,
      notes: "题干和手写答案清晰",
      region_ids: [],
      region_snapshots: [{ page_number: 1 }],
      status: "draft",
      confirmed_question_id: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    {
      id: "10000000-0000-4000-8000-000000000002",
      run_id: "20000000-0000-4000-8000-000000000001",
      source_item_key: "block-2",
      question_key: "2",
      label: "第2题",
      question_text: "说明物体做匀速直线运动时合力的特点。",
      student_answer_text: "合力为零",
      question_type: "short_answer",
      confidence: 0.78,
      notes: null,
      region_ids: [],
      region_snapshots: [{ page_number: 1 }],
      status: "draft",
      confirmed_question_id: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ]
  const confirmedQuestions = questionItems.map((item, index) => ({
    id: `30000000-0000-4000-8000-00000000000${index + 1}`,
    exam_id: exam.id,
    question_key: item.question_key,
    label: item.label,
    question_text: item.question_text,
    question_type: item.question_type,
    recognition_confidence: item.confidence,
    status: "confirmed",
    region_ids: [`40000000-0000-4000-8000-00000000000${index + 1}`],
    confirmed_by_id: null,
    confirmed_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }))
  const recognitionRun = {
    id: questionItems[0].run_id,
    exam_id: exam.id,
    created_by_id: exam.owner_id,
    provider: "fluxnode_gemini",
    model: "gemini-3.5-flash",
    engine: "reference-node",
    status: "completed",
    document_ids: [document.id],
    timing: {
      orientationMs: 120,
      layoutMs: 360,
      cropMs: 24,
      ocrMs: 580,
      totalElapsedMs: 1084,
    },
    error_message: null,
    item_count: questionItems.length,
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    confirmed_at: null as string | null,
  }
  const answerRunId = "50000000-0000-4000-8000-000000000001"
  const answerItems = confirmedQuestions.map((question, index) => ({
    id: `60000000-0000-4000-8000-00000000000${index + 1}`,
    run_id: answerRunId,
    question_id: question.id,
    source_item_key: question.id,
    source_question_key: question.question_key,
    answer_text:
      index === 0 ? "a=F/m=2 m/s²" : "匀速直线运动时物体所受合力为零。",
    max_score: index === 0 ? 3 : 2,
    rubric_text:
      index === 0 ? "公式、代入、结果各 1 分。" : "结论正确得 2 分。",
    scoring_points:
      index === 0
        ? [
            { id: "p1", description: "写出公式", points: 1, required: true },
            { id: "p2", description: "正确代入", points: 1, required: true },
            { id: "p3", description: "结果和单位", points: 1, required: true },
          ]
        : [{ id: "p1", description: "合力为零", points: 2, required: true }],
    confidence: index === 0 ? 0.94 : 0.9,
    match_reason: "按已确认题目直接解题",
    status: "matched",
    revision_id: null,
    error_message: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }))
  const answerRun = {
    id: answerRunId,
    exam_id: exam.id,
    created_by_id: exam.owner_id,
    source_type: "model",
    provider: "pomoai",
    model: "gpt-5.6-sol",
    document_ids: [],
    status: "completed",
    timing: {
      modelMs: 1600,
      totalElapsedMs: 1800,
      usedModels: ["gpt-5.6-sol"],
    },
    error_message: null,
    item_count: answerItems.length,
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    confirmed_at: null as string | null,
  }
  let questionsAreConfirmed = false
  let answerRunCreated = false
  let answerRunConfirmed = false
  let revisionsPublished = false
  const revisions = answerItems.map((item, index) => ({
    id: `70000000-0000-4000-8000-00000000000${index + 1}`,
    standard_answer_id: `80000000-0000-4000-8000-00000000000${index + 1}`,
    question_id: item.question_id,
    revision_number: 1,
    question_key: item.source_question_key,
    question_text: confirmedQuestions[index].question_text,
    question_type: confirmedQuestions[index].question_type,
    answer_text: item.answer_text,
    max_score: item.max_score,
    rubric_text: item.rubric_text,
    scoring_points: item.scoring_points,
    source_provider: "pomoai",
    source_model: "gpt-5.6-sol",
    generation_confidence: item.confidence,
    content_hash: "a".repeat(64),
    status: "draft",
    created_by_id: exam.owner_id,
    published_by_id: null,
    preparation_item_id: item.id,
    created_at: new Date().toISOString(),
    published_at: null as string | null,
  }))

  await page.route(`**/api/v1/exams/${exam.id}/**`, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    if (path.endsWith("/question-recognition-runs") && method === "GET") {
      return route.fulfill({ json: { data: [recognitionRun], count: 1 } })
    }
    if (path.endsWith("/question-recognition-runs") && method === "POST") {
      return route.fulfill({ json: recognitionRun })
    }
    if (path.endsWith(`/question-recognition-runs/${recognitionRun.id}`)) {
      return route.fulfill({ json: recognitionRun })
    }
    if (
      path.endsWith(`/question-recognition-runs/${recognitionRun.id}/items`)
    ) {
      return route.fulfill({ json: questionItems })
    }
    if (path.includes("/question-recognition-items/") && method === "PATCH") {
      const current = questionItems.find((item) => path.endsWith(item.id))!
      Object.assign(current, request.postDataJSON())
      return route.fulfill({ json: current })
    }
    if (
      path.endsWith(`/question-recognition-runs/${recognitionRun.id}/confirm`)
    ) {
      questionsAreConfirmed = true
      recognitionRun.confirmed_at = new Date().toISOString()
      questionItems.forEach((item, index) => {
        item.status = "confirmed"
        item.confirmed_question_id = confirmedQuestions[index].id
      })
      return route.fulfill({ json: recognitionRun })
    }
    if (path.endsWith("/questions")) {
      return route.fulfill({
        json: {
          data: questionsAreConfirmed ? confirmedQuestions : [],
          count: questionsAreConfirmed ? confirmedQuestions.length : 0,
        },
      })
    }
    if (path.endsWith("/answer-preparation-runs") && method === "GET") {
      return route.fulfill({
        json: {
          data: answerRunCreated ? [answerRun] : [],
          count: answerRunCreated ? 1 : 0,
        },
      })
    }
    if (path.endsWith("/answer-preparation-runs") && method === "POST") {
      answerRunCreated = true
      return route.fulfill({ json: answerRun })
    }
    if (path.endsWith(`/answer-preparation-runs/${answerRun.id}`)) {
      return route.fulfill({ json: answerRun })
    }
    if (path.endsWith(`/answer-preparation-runs/${answerRun.id}/items`)) {
      return route.fulfill({ json: answerItems })
    }
    if (path.includes("/answer-preparation-items/") && method === "PATCH") {
      const current = answerItems.find((item) => path.endsWith(item.id))!
      Object.assign(current, request.postDataJSON())
      return route.fulfill({ json: current })
    }
    if (path.endsWith(`/answer-preparation-runs/${answerRun.id}/confirm`)) {
      answerRunConfirmed = true
      answerRun.confirmed_at = new Date().toISOString()
      answerItems.forEach((item, index) => {
        item.status = "confirmed"
        item.revision_id = revisions[index].id
      })
      return route.fulfill({ json: answerRun })
    }
    if (path.endsWith("/standard-answers/revisions")) {
      return route.fulfill({
        json: {
          data: answerRunConfirmed ? revisions : [],
          count: answerRunConfirmed ? revisions.length : 0,
        },
      })
    }
    if (path.endsWith("/standard-answers/publish") && method === "POST") {
      revisionsPublished = true
      revisions.forEach((revision) => {
        revision.status = "published"
        revision.published_at = new Date().toISOString()
      })
      return route.fulfill({
        json: { data: revisions, count: revisions.length },
      })
    }
    return route.continue()
  })

  try {
    await page.addInitScript((value) => {
      localStorage.setItem("access_token", value)
    }, token)
    await page.goto(`/exams/${exam.id}/questions?runId=${recognitionRun.id}`)
    await expect(page.getByRole("heading", { name: exam.title })).toBeVisible()
    await expect(page.getByTestId(/^recognition-item-/)).toHaveCount(
      questionItems.length,
    )
    await expect(page.getByText("平均置信度")).toBeVisible()
    await expect(page.getByTestId("average-confidence")).toHaveText("85%")
    // 题目列表默认收起，先展开第一行再断言卷面作答
    await page
      .getByTestId(/^recognition-item-/)
      .first()
      .click()
    await expect(
      page.getByText(questionItems[0].student_answer_text),
    ).toBeVisible()
    // 耗时明细默认折叠在「批次详情（调试）」里，先展开再断言
    await page.getByText("批次详情（调试）").click()
    await expect(page.getByText("方向检测")).toBeVisible()
    await expect(page.getByText("版面分割")).toBeVisible()
    await expect(page.getByText("OCR", { exact: true })).toBeVisible()
    await page.getByRole("button", { name: "确认题目并进入标准答案" }).click()
    // 生成参考答案前，标准答案页只展示模式选择与确认题目数
    await expect(
      page.getByRole("button", { name: "生成参考答案" }),
    ).toBeVisible()
    await page.getByRole("button", { name: "生成参考答案" }).click()
    await expect(page.getByText("答案匹配与评分准则")).toBeVisible()
    await expect(page.getByText("pomoai", { exact: true })).toBeVisible()
    await expect(
      page.getByText("gpt-5.6-sol", { exact: true }).last(),
    ).toBeVisible()
    await expect(page.getByTestId(/^answer-item-/)).toHaveCount(
      answerItems.length,
    )
    await expect(page.getByText("模型耗时")).toBeVisible()
    await page.getByRole("button", { name: "确认答案与评分准则" }).click()
    await expect(page.getByText("待发布", { exact: true })).toHaveCount(
      revisions.length,
    )
    await page
      .getByRole("button", {
        name: new RegExp(`发布 ${revisions.length} 个待发布版本`),
      })
      .click()
    expect(revisionsPublished).toBeTruthy()
    await expect(page.getByText("已发布锁定")).toHaveCount(revisions.length)
    await page.screenshot({
      path: "/tmp/question-answer-workflow.png",
      fullPage: true,
    })
  } finally {
    await page.request.delete(`${apiBase}/exams/${exam.id}`, { headers })
  }
})
