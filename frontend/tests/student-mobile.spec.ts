import { expect, test } from "@playwright/test"

/**
 * 学生端移动可用性。学生基本都在手机上打开，桌面侧栏折叠成汉堡后没人会去点，
 * 因此这几条是学生端能不能真的用起来的判据。
 *
 * 只覆盖窄视口而不用 `devices["iPhone 13"]`：设备预设需要完整 Chromium，
 * headless shell 跑不了，而这里要验的是响应式布局，视口宽度就够。
 */
test.use({ viewport: { width: 390, height: 844 } })

const entryId = "11111111-1111-4111-8111-111111111111"

const listPayload = {
  data: [
    {
      entry_id: entryId,
      exam_id: "22222222-2222-4222-8222-222222222222",
      exam_title: "八年级物理期中",
      subject: "物理",
      exam_date: "2026-05-10",
      question_label: "第16题",
      score: 4,
      max_score: 8,
      is_wrong: true,
      knowledge_point_names: ["功和功率"],
      has_image: false,
      released_at: "2026-05-12T02:00:00Z",
      review_count: 0,
      next_due_at: null,
    },
  ],
  count: 1,
  subjects: ["物理"],
  knowledge_points: ["功和功率"],
}

const detailPayload = {
  entry_id: entryId,
  exam_id: "22222222-2222-4222-8222-222222222222",
  exam_title: "八年级物理期中",
  subject: "物理",
  grade_level: "八年级",
  exam_date: "2026-05-10",
  class_name_at_time: "八年级一班",
  question_label: "第16题",
  question_text: "求物体运动的功率。",
  question_type: "calculation",
  score: 4,
  max_score: 8,
  is_wrong: true,
  standard_answer_text: "P = W / t = 100W",
  scoring_points: [],
  student_answer_text: "P=W/t",
  missed_points: [{ point: "代入数据并计算", reason: "只写出公式", points: 4 }],
  teacher_comment: "过程不完整",
  knowledge_point_names: ["功和功率"],
  has_image: false,
  released_at: "2026-05-12T02:00:00Z",
}

test("学生在手机上有底部导航、收起的筛选和常驻评分按钮", async ({ page }) => {
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
  await page.route("**/api/v1/students/me/profile", async (route) =>
    route.fulfill({
      json: {
        learner_id: "33333333-3333-4333-8333-333333333333",
        display_name: "刘雨欣",
        grade_band: null,
        entry_count: 5,
        wrong_count: 1,
        enrollments: [
          {
            org_name: "示范一中",
            class_name: "八年级一班",
            student_name: "刘雨欣",
            started_at: "2026-02-01T00:00:00Z",
            ended_at: null,
          },
        ],
      },
    }),
  )
  await page.route("**/api/v1/students/me/wrongbook/due**", async (route) =>
    route.fulfill({
      json: {
        data: listPayload.data,
        count: 1,
        subjects: [],
        knowledge_points: [],
      },
    }),
  )
  await page.route("**/api/v1/students/me/wrongbook/entries**", async (route) =>
    route.fulfill({ json: listPayload }),
  )
  await page.route(
    `**/api/v1/students/me/wrongbook/entries/${entryId}`,
    async (route) => route.fulfill({ json: detailPayload }),
  )

  await page.goto("/my/wrongbook")

  // 底部导航：手机上不该要求学生去点左上角汉堡
  const tabBar = page.getByRole("navigation")
  await expect(tabBar.getByRole("link", { name: "成绩" })).toBeVisible()
  await expect(tabBar.getByRole("link", { name: "错题本" })).toBeVisible()

  // 筛选默认收起，第一道错题要落在首屏
  await expect(page.getByRole("button", { name: "筛选" })).toBeVisible()
  await expect(page.getByText("知识点", { exact: true })).toHaveCount(0)
  await expect(page.getByText("第16题")).toBeInViewport()

  await page.getByRole("button", { name: "筛选" }).click()
  await expect(page.getByText("知识点", { exact: true })).toBeVisible()

  // 进入复习：标题与页签让位给题目，评分按钮常驻可见
  await page.getByText("今天要复习 1 题").click()
  await expect(page.getByRole("heading", { name: "我的错题本" })).toHaveCount(0)
  await expect(page.getByText("第 1 / 1 题")).toBeVisible()
  await expect(page.getByRole("button", { name: "会了" })).toBeInViewport()

  expect(errors).toEqual([])
})
