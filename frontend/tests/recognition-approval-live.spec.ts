import path from "node:path"

import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

test("recognition preview requires per-question approval before grading", async ({
  page,
}) => {
  test.skip(
    true,
    "「逐题批准」识别预览工作流已随 UI 重构移除（grading 页不再有该交互），用例已过时",
  )
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
  const exams = await (
    await page.request.get(`${apiBase}/exams/?limit=100`, { headers })
  ).json()
  const exam = exams.data.find(
    (item: { title: string }) => item.title === "扫描流程验证-物理双页卷",
  )
  expect(exam).toBeTruthy()

  await page.addInitScript(
    (value) => localStorage.setItem("access_token", value),
    token,
  )
  await page.goto(`/exams/${exam.id}/grading`)
  await expect(page.getByRole("heading", { name: "批量批改" })).toBeVisible()
  await expect(page.getByText("还有 4 道题需要逐题批准")).toBeVisible({
    timeout: 20_000,
  })

  const question19 = page.getByRole("row").filter({ hasText: "第19题" })
  await expect(question19.getByLabel("第19题学生答案")).toHaveValue(
    "同一\n匀速直线运动\nC",
  )
  await expect(
    question19.getByRole("button", { name: "保存并批准判分" }),
  ).toBeVisible()

  const question21 = page.getByRole("row").filter({ hasText: "第21题" })
  await expect(
    question21.getByText("当前证据不可直接自动判分，请先人工确认。"),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "确认识别结果，进入批改" }),
  ).toBeDisabled()

  await page.screenshot({
    path: path.resolve(
      process.cwd(),
      "../outputs/recognition-approval-workflow.png",
    ),
    fullPage: true,
  })
})
