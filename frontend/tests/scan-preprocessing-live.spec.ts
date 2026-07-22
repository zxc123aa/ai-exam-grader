import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

test("hybrid scan metadata is visible for a real two-page upload", async ({
  page,
}) => {
  const token = process.env.LIVE_TEST_TOKEN ?? ""
  const examId = process.env.LIVE_TEST_EXAM_ID ?? ""
  expect(token).not.toBe("")
  expect(examId).not.toBe("")

  await page.goto("/login")
  await page.evaluate(
    (value) => localStorage.setItem("access_token", value),
    token,
  )
  await page.goto(`/exams/${examId}/marking`)
  await page.getByRole("button", { name: "试卷页面" }).click()

  const dialog = page.getByRole("dialog")
  await expect(dialog.getByText("1 个源文件，共 2 页")).toBeVisible()
  await expect(dialog.getByText("2-scanned.pdf", { exact: true })).toBeVisible()
  await expect(dialog.getByText(/需要复核 · 91%/)).toBeVisible()
  await expect(dialog.getByText("视觉双页边界", { exact: true })).toBeVisible()
  await expect(dialog.getByText("已保留原图", { exact: true })).toBeVisible()
  await expect(dialog.getByText(/扫描 \d+\.\d 秒/)).toBeVisible()
  await expect(dialog.getByText(/顶部内容靠近裁切边缘/)).toBeVisible()
  await expect(dialog.getByText("分割结果", { exact: true })).toBeVisible()
  await expect(dialog.getByRole("img", { name: "分割第 1 页" })).toBeVisible()
  await expect(dialog.getByRole("img", { name: "分割第 2 页" })).toBeVisible()

  await dialog.screenshot({
    path: "../outputs/scan-validation/scan-metadata-dialog.png",
  })
})
