import { expect, test } from "@playwright/test"
import { schoolOwnerEmail, schoolOwnerPassword } from "./config.ts"

test.use({ storageState: { cookies: [], origins: [] } })

type ExamDocument = {
  document_type: string
  page_count?: number | null
  stored_file: { original_filename: string }
}

// 1x1 有效 PNG：本用例只验证多源文件连续翻页，不需要真实卷面内容
const pngBuffer = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z1ZkAAAAASUVORK5CYII=",
  "base64",
)

test("multiple source files behave as consecutive pages of one exam", async ({
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

  // 老演示考试是旧版管线数据，当前前端打开标记页即崩溃
  // （Maximum update depth exceeded，见 issue 记录），改为现场建考试自包含验证
  const examResponse = await page.request.post(`${apiBase}/exams/`, {
    headers,
    data: { title: `连续翻页验收-${Date.now()}`, subject: "物理" },
  })
  expect(examResponse.ok()).toBeTruthy()
  const exam = await examResponse.json()

  try {
    for (const name of ["part-a.png", "part-b.png"]) {
      const fileResponse = await page.request.post(
        `${apiBase}/exams/${exam.id}/files`,
        {
          headers,
          multipart: {
            file: { name, mimeType: "image/png", buffer: pngBuffer },
            document_type: "blank_exam",
          },
        },
      )
      expect(fileResponse.ok()).toBeTruthy()
    }

    const filesResponse = await page.request.get(
      `${apiBase}/exams/${exam.id}/files`,
      { headers },
    )
    const documents = (
      (await filesResponse.json()).data as ExamDocument[]
    ).filter((item) => item.document_type === "blank_exam")
    expect(documents.length).toBeGreaterThan(1)

    // 后台扫描（queued/running）期间禁止调整顺序，等它落定（全量并发下较慢）
    await expect
      .poll(
        async () => {
          const response = await page.request.get(
            `${apiBase}/exams/${exam.id}/files`,
            { headers },
          )
          return ((await response.json()).data as ExamDocument[]).every(
            (item) =>
              !["queued", "running"].includes(
                (item as { preprocessing_status?: string })
                  .preprocessing_status ?? "",
              ),
          )
        },
        { timeout: 60_000 },
      )
      .toBe(true)

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

    await expect(
      page.getByText(fileNamePerPage[0], { exact: true }),
    ).toBeVisible({ timeout: 15_000 })
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
  } finally {
    await page.request.delete(`${apiBase}/exams/${exam.id}`, { headers })
  }
})
