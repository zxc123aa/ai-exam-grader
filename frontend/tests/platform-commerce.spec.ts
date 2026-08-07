import { expect, test } from "@playwright/test"

test("平台管理员可以查看订单、商品和售后工作台", async ({ page }) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))

  await page.goto("/platform/commerce")
  await expect(page.getByRole("heading", { name: "订单与财务" })).toBeVisible()
  await expect(page.getByText("待确认收款", { exact: true })).toBeVisible()
  await expect(page.getByRole("tab", { name: "学校订单" })).toBeVisible()

  await page.getByRole("tab", { name: "销售商品" }).click()
  await expect(page.getByRole("heading", { name: "年度套餐" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "答卷加量包" })).toBeVisible()
  await page.getByRole("button", { name: "新建套餐" }).click()
  const dialog = page.getByRole("dialog")
  await expect(
    dialog.getByRole("heading", { name: "新建年度套餐" }),
  ).toBeVisible()
  await expect(dialog.getByLabel("商品编码")).toBeVisible()
  await expect(dialog.getByRole("button", { name: "保存草稿" })).toBeDisabled()
  await dialog.getByRole("button", { name: "取消" }).click()

  await page.getByRole("tab", { name: "发票与退款" }).click()
  await expect(page.getByRole("heading", { name: "发票申请" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "退款申请" })).toBeVisible()
  expect(errors).toEqual([])
})
