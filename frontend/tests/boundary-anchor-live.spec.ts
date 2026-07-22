import { expect, test } from "@playwright/test"

test.use({ storageState: { cookies: [], origins: [] } })

test("page 2 keeps the complete answer for question 21 above question 22", async ({
  page,
}) => {
  test.setTimeout(180_000)
  const login = await page.request.post(
    "http://localhost:8000/api/v1/login/access-token",
    {
      form: {
        username: process.env.LIVE_TEST_EMAIL ?? "",
        password: process.env.LIVE_TEST_PASSWORD ?? "",
      },
    },
  )
  expect(login.ok()).toBeTruthy()
  const { access_token: token } = await login.json()

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

  const exams = await page.request.get("http://localhost:8000/api/v1/exams/", {
    headers: { Authorization: `Bearer ${token}` },
  })
  const exam = (await exams.json()).data.find(
    (item: { title: string }) => item.title === "高一年级物理期中检测题",
  )
  expect(exam).toBeTruthy()

  const filesResponse = await page.request.get(
    `http://localhost:8000/api/v1/exams/${exam.id}/files`,
    { headers: { Authorization: `Bearer ${token}` } },
  )
  const documents = (await filesResponse.json()).data.filter(
    (item: { document_type: string }) => item.document_type === "blank_exam",
  )
  let targetPageNumber = 1
  let found = false
  for (const document of documents) {
    if (document.stored_file.original_filename === "2.jpg") {
      found = true
      break
    }
    targetPageNumber += document.page_count ?? 1
  }
  expect(found).toBeTruthy()

  await page.goto(`/exams/${exam.id}/marking`)
  await expect(page.getByRole("button", { name: "试卷页面" })).toBeVisible()
  for (let pageNumber = 1; pageNumber < targetPageNumber; pageNumber += 1) {
    await page.getByRole("button", { name: "下一页" }).click()
  }
  await expect(page.getByText("2.jpg", { exact: true })).toBeVisible()

  const responsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/region-candidates") && response.ok(),
  )
  await page.getByRole("button", { name: "检测题目区域" }).click()
  const payload = await (await responsePromise).json()
  const q21 = payload.data.find((item: { label: string }) =>
    item.label.includes("21"),
  )
  const q22 = payload.data.find((item: { label: string }) =>
    item.label.includes("22"),
  )
  expect(q21).toBeTruthy()
  expect(q22).toBeTruthy()
  const boundary = q21.y + q21.height
  expect(boundary).toBeCloseTo(q22.y, 3)
  expect(boundary).toBeGreaterThanOrEqual(0.415)
  expect(boundary).toBeLessThanOrEqual(0.425)

  await expect(page.getByTestId("candidate-list-第21题")).toBeVisible()
  await expect(page.getByTestId("candidate-list-第22题")).toBeVisible()
  await page.screenshot({
    path: "/tmp/21-22-boundary-effect.png",
    fullPage: true,
  })
})
