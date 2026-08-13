import { expect, test } from "@playwright/test"

const entryId = "11111111-1111-4111-8111-111111111111"

const listPayload = {
  data: [
    {
      entry_id: entryId,
      exam_id: "22222222-2222-4222-8222-222222222222",
      exam_title: "期中物理",
      subject: "物理",
      exam_date: "2026-05-10",
      question_label: "第1题",
      score: 6,
      max_score: 10,
      is_wrong: true,
      knowledge_point_names: ["功和功率"],
      has_image: false,
      released_at: "2026-05-12T02:00:00Z",
    },
  ],
  count: 1,
  subjects: ["物理"],
  knowledge_points: ["功和功率"],
}

const detailPayload = {
  entry_id: entryId,
  exam_id: "22222222-2222-4222-8222-222222222222",
  exam_title: "期中物理",
  subject: "物理",
  grade_level: "八年级",
  exam_date: "2026-05-10",
  class_name_at_time: "001班",
  question_label: "第1题",
  question_text: "一物体做匀速直线运动，求其功率。",
  question_type: "calculation",
  score: 6,
  max_score: 10,
  is_wrong: true,
  standard_answer_text: "P = W / t = 200W",
  scoring_points: [],
  student_answer_text: "P=W/t",
  missed_points: [{ point: "代入数据", reason: "缺少代入过程", points: 4 }],
  teacher_comment: "过程不完整",
  knowledge_point_names: ["功和功率"],
  has_image: false,
  released_at: "2026-05-12T02:00:00Z",
}

async function mockWrongbook(
  page: import("@playwright/test").Page,
  options: { due?: number } = {},
) {
  const dueCount = options.due ?? 0
  await page.route("**/api/v1/users/me", async (route) =>
    route.fulfill({
      json: {
        id: "student-1",
        email: "student@example.com",
        full_name: "刘雨欣",
        is_active: true,
        is_superuser: false,
        role: "student",
      },
    }),
  )
  await page.route("**/api/v1/students/me/wrongbook/due**", async (route) =>
    route.fulfill({
      json: {
        data: dueCount > 0 ? listPayload.data : [],
        count: dueCount,
        subjects: [],
        knowledge_points: [],
      },
    }),
  )
  await page.route("**/api/v1/students/me/wrongbook/mastery**", async (route) =>
    route.fulfill({
      json: {
        data: [
          {
            subject: "物理",
            knowledge_point_name: "功和功率",
            attempts: 4,
            wrong_count: 3,
            wrong_rate: 75,
            last_wrong_at: "2026-05-12T02:00:00Z",
            last_reviewed_at: null,
          },
        ],
        count: 1,
      },
    }),
  )
  await page.route("**/api/v1/students/me/wrongbook/cram**", async (route) =>
    route.fulfill({
      json: { ...listPayload, subjects: [], knowledge_points: [] },
    }),
  )
  // Playwright 按注册的倒序匹配，所以列表这条最宽的要先注册，具体路径后注册才生效
  await page.route("**/api/v1/students/me/wrongbook/entries**", async (route) =>
    route.fulfill({ json: listPayload }),
  )
  await page.route(
    `**/api/v1/students/me/wrongbook/entries/${entryId}`,
    async (route) => route.fulfill({ json: detailPayload }),
  )
  await page.route(
    `**/api/v1/students/me/wrongbook/entries/${entryId}/review`,
    async (route) =>
      route.fulfill({
        json: {
          entry_id: entryId,
          result: "good",
          review_count: 1,
          interval_days: 1,
          next_due_at: "2026-05-13T02:00:00Z",
          due_count: 0,
        },
      }),
  )
}

test("学生可以在错题本里看到丢分的评分点", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))

  await mockWrongbook(page)
  await page.goto("/my/wrongbook")
  await expect(page.getByRole("heading", { name: "我的错题本" })).toBeVisible()
  await expect(page.getByText("共 1 道错题")).toBeVisible()
  await expect(page.getByText("期中物理 · 物理 ·")).toBeVisible()
  await expect(page.getByText("功和功率").first()).toBeVisible()

  await page.getByRole("button", { name: "看看为什么错" }).click()
  await expect(page.getByText("这道题丢在哪")).toBeVisible()
  await expect(page.getByText("代入数据")).toBeVisible()
  await expect(page.getByText("缺少代入过程")).toBeVisible()
  await expect(page.getByText("P = W / t = 200W")).toBeVisible()
  await expect(page.getByText("过程不完整")).toBeVisible()

  expect(errors).toEqual([])
})

test("学生可以按提示完成今天的复习并查看薄弱知识点", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))

  await mockWrongbook(page, { due: 1 })
  await page.goto("/my/wrongbook")

  // 有到期错题时首屏就提示今天要复习几题
  await expect(page.getByText("今天要复习 1 题")).toBeVisible()
  await page.getByText("今天要复习 1 题").click()

  // 复习面板直接展开题目，只问「还会不会」
  await expect(page.getByText("第 1 / 1 题")).toBeVisible()
  await expect(page.getByText("这道题丢在哪")).toBeVisible()
  await page.getByRole("button", { name: "会了" }).click()
  await expect(page.getByText("今天的复习做完了")).toBeVisible()

  await page.getByRole("button", { name: "薄弱知识点" }).click()
  await expect(page.getByText("错 75%")).toBeVisible()
  await expect(page.getByText("做过 4 题 · 错 3 题 · 还没复习过")).toBeVisible()

  await page.getByRole("button", { name: "考前清单" }).click()
  await expect(page.getByRole("button", { name: "打印清单" })).toBeVisible()
  await expect(page.getByText("1. 期中物理 第1题")).toBeVisible()

  expect(errors).toEqual([])
})
