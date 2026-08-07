import { expect, test } from "@playwright/test"

test("平台管理员可以查看并发放学校答卷额度", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))

  await page.goto("/platform/00000000-0000-0000-0000-000000000001")
  const billing = page.getByTestId("platform-org-billing")
  await expect(
    billing.getByRole("heading", { name: "合同与答卷额度" }),
  ).toBeVisible()
  await expect(billing.getByText("可批改答卷")).toBeVisible()
  await expect(billing.getByText("平台模型用量")).toBeVisible()

  await billing.getByRole("button", { name: "发放额度" }).click()
  const dialog = page.getByRole("dialog")
  await expect(
    dialog.getByRole("heading", { name: "发放答卷额度" }),
  ).toBeVisible()
  await expect(
    dialog.getByText(/只对成功形成建议结果的有效答卷计费/),
  ).toBeVisible()
  await expect(dialog.getByRole("button", { name: "确认发放" })).toBeDisabled()
  await dialog.getByLabel("答卷数量").fill("1")
  await dialog.getByLabel("备注").fill("浏览器验收额度")
  await dialog.getByRole("button", { name: "确认发放" }).click()

  await expect(dialog).toBeHidden()
  await expect(page.getByText("答卷额度已发放")).toBeVisible()
  expect(errors).toEqual([])
})
