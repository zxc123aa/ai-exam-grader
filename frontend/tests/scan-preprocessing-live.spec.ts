import { expect, test } from "@playwright/test"
import { schoolOwnerEmail, schoolOwnerPassword } from "./config.ts"

test.use({ storageState: { cookies: [], origins: [] } })

test("hybrid scan metadata is visible for a real two-page upload", async ({
  page,
}) => {
  const apiBase = "http://localhost:8000/api/v1"
  const login = await page.request.post(`${apiBase}/login/access-token`, {
    form: {
      username: schoolOwnerEmail,
      password: schoolOwnerPassword,
    },
  })
  expect(login.ok()).toBeTruthy()
  const { access_token: token } = await login.json()
  const headers = { Authorization: `Bearer ${token}` }

  // 找到包含 2-scanned.pdf（双页扫描件）的考试；数据不存在时跳过
  const examsResponse = await page.request.get(`${apiBase}/exams/?limit=1000`, {
    headers,
  })
  expect(examsResponse.ok()).toBeTruthy()
  let examId: string | null = null
  for (const exam of (await examsResponse.json()).data) {
    const filesResponse = await page.request.get(
      `${apiBase}/exams/${exam.id}/files`,
      { headers },
    )
    const documents = (await filesResponse.json()).data.filter(
      (item: { document_type: string }) => item.document_type === "blank_exam",
    )
    if (
      documents.some(
        (item: { stored_file: { original_filename: string } }) =>
          item.stored_file.original_filename === "2-scanned.pdf",
      )
    ) {
      examId = exam.id
      break
    }
  }
  test.skip(
    !examId,
    "演示数据中不存在包含 2-scanned.pdf 的考试（历史数据已被替换）",
  )

  await page.goto("/login")
  await page.evaluate(
    (value) => localStorage.setItem("access_token", value),
    token,
  )
  await page.goto(`/exams/${examId}/marking`)
  await page.getByRole("button", { name: "导入试卷" }).click()

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
