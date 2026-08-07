import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

const baseUrl = "https://app.dianfandig.com"
const examId = "7a1c8e43-88de-45dd-924b-adbc401d939a"

test("公网物理批卷结果显示真实题目进度和复核数", async ({ page }) => {
  const serverErrors: string[] = []
  page.on("response", (response) => {
    if (response.status() >= 500 || response.status() === 403) {
      serverErrors.push(`${response.status()} ${response.url()}`)
    }
  })

  await page.goto(`${baseUrl}/login`)
  await page.getByTestId("email-input").fill("demo2.physics@example.com")
  await page.getByTestId("password-input").fill("Dianfan@2026")
  await page.getByRole("button", { name: "登录" }).click()
  await page.waitForURL((url) => url.pathname === "/")

  await page.goto(`${baseUrl}/exams/${examId}/grading`)
  const batch = page.getByText("最近批次").locator("..").locator("..")
  await expect(batch.getByText("6 / 6 题块")).toBeVisible()
  await expect(batch.getByText("客观题 6 / 主观题 0")).toBeVisible()
  await expect(
    batch.getByText("待复核").locator("..").getByText("4"),
  ).toBeVisible()
  await expect(
    batch.getByText("失败").locator("..").getByText("0"),
  ).toBeVisible()
  expect(serverErrors).toEqual([])
})
