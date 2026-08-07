import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

type ExamDocument = {
  document_type: string
  page_count?: number | null
  stored_file: { original_filename: string }
}

test("multiple source files behave as consecutive pages of one exam", async ({
  page,
}) => {
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
  const exam = (await examsResponse.json()).data.find(
    (item: { title: string }) => item.title === "高一年级物理期中检测题",
  )
  expect(exam).toBeTruthy()

  const filesResponse = await page.request.get(
    `${apiBase}/exams/${exam.id}/files`,
    { headers },
  )
  const documents = (
    (await filesResponse.json()).data as ExamDocument[]
  ).filter((item) => item.document_type === "blank_exam")
  expect(documents.length).toBeGreaterThan(1)

  // 每个文档的页数、全卷总页数，以及每页归属哪个文件，都从 API 实际数据推导
  const pagesPerDocument = documents.map((item) => item.page_count ?? 1)
  const totalPages = pagesPerDocument.reduce((sum, count) => sum + count, 0)
  const fileNamePerPage: string[] = []
  documents.forEach((item, index) => {
    for (let i = 0; i < pagesPerDocument[index]; i += 1) {
      fileNamePerPage.push(item.stored_file.original_filename)
    }
  })

  await page.goto("/login").catch(() => undefined)
  await expect
    .poll(async () => {
      try {
        return await page.evaluate(
          () => performance.getEntriesByType("navigation")[0]?.type,
        )
      } catch {
        return null
      }
    })
    .toBe("reload")
  await page.evaluate(
    (value) => localStorage.setItem("access_token", value),
    token,
  )
  await page.goto(`/exams/${exam.id}/marking`)

  await expect(page.getByText(fileNamePerPage[0], { exact: true })).toBeVisible(
    { timeout: 15_000 },
  )
  await expect(page.getByText(`第 1 / ${totalPages} 页`)).toBeVisible()
  await expect(page.getByRole("button", { name: "上一页" })).toBeDisabled()

  // 连续翻到最后一页：逐页校验页码指示器与所属文件名
  for (let pageNumber = 2; pageNumber <= totalPages; pageNumber += 1) {
    await page.getByRole("button", { name: "下一页" }).click()
    await expect(
      page.getByText(fileNamePerPage[pageNumber - 1], { exact: true }),
    ).toBeVisible()
    await expect(
      page.getByText(`第 ${pageNumber} / ${totalPages} 页`),
    ).toBeVisible()
  }
  await expect(page.getByRole("button", { name: "下一页" })).toBeDisabled()

  // 翻回第一页
  await page.getByRole("button", { name: "上一页" }).click()
  await expect(
    page.getByText(fileNamePerPage[totalPages - 2], { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByText(`第 ${totalPages - 1} / ${totalPages} 页`),
  ).toBeVisible()

  // 源文件管理对话框：汇总文案、每个文件名、顺序调整按钮
  await page.getByRole("button", { name: "导入试卷" }).click()
  const dialog = page.getByRole("dialog")
  await expect(
    dialog.getByText(`${documents.length} 个源文件，共 ${totalPages} 页`),
  ).toBeVisible()
  for (const document of documents) {
    await expect(
      dialog.getByText(document.stored_file.original_filename, {
        exact: true,
      }),
    ).toBeVisible()
  }
  await expect(
    dialog.getByRole("button", { name: "向前移动" }).first(),
  ).toBeDisabled()
  await expect(
    dialog.getByRole("button", { name: "向后移动" }).first(),
  ).toBeEnabled()
})
