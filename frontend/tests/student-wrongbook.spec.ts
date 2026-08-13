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

test("学生可以在错题本里看到丢分的评分点", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))

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
  await page.route(
    "**/api/v1/students/me/wrongbook/entries?**",
    async (route) => route.fulfill({ json: listPayload }),
  )
  await page.route("**/api/v1/students/me/wrongbook/entries", async (route) =>
    route.fulfill({ json: listPayload }),
  )
  await page.route(
    `**/api/v1/students/me/wrongbook/entries/${entryId}`,
    async (route) => route.fulfill({ json: detailPayload }),
  )

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
