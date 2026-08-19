/**
 * 点凡阅卷 深度回归：老毛病逐项实测（动态流程，会产生少量模型调用）。
 *
 * 用法：node scripts/regression-flows.mjs（打公网；SMOKE_BASE_URL 可换环境）
 *
 * 覆盖的历史事故：
 *  1. 拍题答疑整页流程：裸 LaTeX / 裸表格 / 失败卡 / 速度（并发）
 *  2. 生成中途跳走再回来，卡片不丢（v0.4.20 只写一次缓存的缺陷）
 *  3. 拍题记录：留档、详情可开、可删除
 *  4. 拍照批改：识别不漏题（>8 道）、按卷面分值（不全是 10 分）
 *  5. 教师端：确认题目页漏题提示不误报
 */
import { createRequire } from "node:module"

const require = createRequire(
  new URL("../frontend/package.json", import.meta.url),
)
const { chromium } = require("playwright")

const BASE = (process.env.SMOKE_BASE_URL || "https://app.dianfandig.com").replace(/\/$/, "")
const STUDENT = {
  email: process.env.SMOKE_STUDENT_EMAIL || "zhangyi@example.com",
  password: process.env.SMOKE_STUDENT_PASSWORD || "student123",
}
const TEACHER = {
  email: process.env.SMOKE_TEACHER_EMAIL || "demo.owner@example.com",
  password: process.env.SMOKE_TEACHER_PASSWORD || "demo12345",
}
const EXAM_ID = process.env.SMOKE_EXAM_ID || "580eaa0b-2bf4-4899-a729-9d97ac7d6f5f"
const PHOTO = process.env.SMOKE_PHOTO || "/mnt/d/Songtan/ai-exam-grader/materials/内测小学数学/张三1.jpg"

const results = []
function check(name, ok, detail = "") {
  results.push({ name, ok })
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  — ${detail}` : ""}`)
}

async function login(page, account) {
  await page.goto(`${BASE}/login`, { waitUntil: "commit", timeout: 60000 })
  await page.waitForSelector('input[type="email"]', { timeout: 60000 })
  await page.fill('input[type="email"]', account.email)
  await page.fill('input[type="password"]', account.password)
  await page.click('button[type="submit"]')
  await page.waitForTimeout(6000)
  return !page.url().includes("/login")
}

async function gotoSnap(page) {
  await page.goto(`${BASE}/my/snap`, { waitUntil: "commit", timeout: 60000 })
  await page.waitForSelector('[data-testid="tab-solve"]', { timeout: 60000 })
}

async function main() {
  console.log(`\n=== 深度回归（老毛病逐项）：${BASE} ===\n`)
  const browser = await chromium.launch({
    executablePath: "/home/st/.cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell",
  })
  const ctx = await browser.newContext({ viewport: { width: 900, height: 1000 } })
  const p = await ctx.newPage()
  p.on("pageerror", (e) => console.log("PAGEERROR:", e.message.slice(0, 150)))

  check("学生登录", await login(p, STUDENT))

  // ===== 1. 拍题答疑整页 + 渲染 =====
  await gotoSnap(p)
  await p.locator('[data-testid="snap-upload-input"]').setInputFiles(PHOTO)
  await p.waitForTimeout(800)
  await p.click('[data-testid="snap-submit"]')
  const t0 = Date.now()
  await p.waitForSelector('[data-testid="snap-stream-result"]', { timeout: 90000 })
  const cardsAt = Math.round((Date.now() - t0) / 1000)

  // 等全部解答完成（「生成中…」带省略号，避开「生成中断」的子串误匹配）
  await p.waitForFunction(
    () =>
      !document.body.innerText.includes("生成中…") &&
      !document.body.innerText.includes("排队中…"),
    null,
    { timeout: 300000 },
  )
  const totalS = Math.round((Date.now() - t0) / 1000)
  const text = await p.locator('[data-testid="snap-stream-result"]').innerText()
  const latexMatches = [...text.matchAll(/\\frac|\\div|\\times|\\sqrt|\\\(|\\\[/g)]
  const latexLeaks = latexMatches.length
  if (latexLeaks > 0) {
    const i = latexMatches[0].index ?? 0
    console.log("  残留上下文:", JSON.stringify(text.slice(Math.max(0, i - 60), i + 60)))
  }
  check("无裸 LaTeX 残留", latexLeaks === 0, `残留 ${latexLeaks}`)
  check("无裸表格符号", !/\|\s*-{2,}/.test(text))
  check(
    "公式已渲染",
    (await p.locator('[data-testid="snap-stream-result"] .katex').count()) > 0,
  )
  if (text.includes("没有生成解答")) {
    const i = text.indexOf("没有生成解答")
    console.log("  失败卡上下文:", JSON.stringify(text.slice(Math.max(0, i - 80), i + 80)))
  }
  check("无失败卡", !text.includes("没有生成解答"), "")
  check("解答耗时", totalS < 300, `${totalS}s（识别 ${cardsAt}s）`)

  // ===== 2. 跳走再回来：缓存恢复（全部完成后跳走，回来卡片应原样在） =====
  await p.goto(`${BASE}/my/wrongbook`, { waitUntil: "commit", timeout: 60000 })
  await p.waitForTimeout(3000)
  await gotoSnap(p)
  await p.waitForTimeout(2000)
  const restoredText = await p
    .locator('[data-testid="snap-stream-result"]')
    .innerText()
    .catch(() => "")
  check("跳走缓存恢复", restoredText.length > 300, `恢复内容 ${restoredText.length} 字`)

  // ===== 3. 拍题记录：留档/详情/删除 =====
  await p.goto(`${BASE}/my/snap-history`, { waitUntil: "commit", timeout: 60000 })
  await p.waitForTimeout(3000)
  const recordCount = await p.locator('[data-testid="snap-record-item"]').count()
  check("拍题记录已留档", recordCount > 0, `${recordCount} 条`)
  if (recordCount > 0) {
    await p.locator('[data-testid="snap-record-item"]').first().click()
    await p.waitForTimeout(2500)
    const detailOk = (await p.locator(".katex").count()) > 0 ||
      (await p.locator("main").last().innerText()).length > 100
    check("记录详情可开", detailOk)
    await p.click("text=返回列表")
    await p.waitForTimeout(1200)
    // 删除最新一条（本次测试产生的）
    await p.locator('[data-testid="snap-record-delete"]').first().click()
    await p.waitForTimeout(600)
    await p.locator('[data-testid="snap-record-delete-confirm"]').click()
    await p.waitForTimeout(2000)
    const after = await p.locator('[data-testid="snap-record-item"]').count()
    check("记录可删除", after === recordCount - 1, `${recordCount} → ${after}`)
  }

  // ===== 4. 拍照批改：不漏题 + 卷面分值 =====
  await gotoSnap(p)
  await p.click('[data-testid="tab-grade"]')
  await p.locator('[data-testid="snap-upload-input"]').setInputFiles(PHOTO)
  await p.waitForTimeout(800)
  await p.click('[data-testid="snap-submit"]')
  await p.waitForSelector('[data-testid="snap-grade-stream-result"]', { timeout: 90000 })
  const gradeCount = await p.locator('[data-testid="snap-grade-stream-result"] > div').count()
  check("批改识别不漏题", gradeCount > 8, `${gradeCount} 题（旧上限 8）`)
  await p.waitForFunction(
    () => !document.body.innerText.includes("批改中"),
    null,
    { timeout: 300000 },
  )
  const maxes = (
    await p.locator('[data-testid="snap-grade-stream-result"] .text-sm').allInnerTexts()
  ).filter((t) => t.trim().startsWith("/"))
  const distinct = new Set(maxes)
  check("按卷面分值（不全是 10 分）", !(distinct.size === 1 && distinct.has("/ 10 分")),
    JSON.stringify([...distinct].slice(0, 6)))
  const gradeText = await p.locator('[data-testid="snap-grade-stream-result"]').innerText()
  check("批改无失败卡", !gradeText.includes("批改失败"))
  // 清掉这条批改留档
  await p.goto(`${BASE}/my/snap-history`, { waitUntil: "commit", timeout: 60000 })
  await p.waitForTimeout(2500)
  if ((await p.locator('[data-testid="snap-record-delete"]').count()) > 0) {
    await p.locator('[data-testid="snap-record-delete"]').first().click()
    await p.waitForTimeout(500)
    await p.locator('[data-testid="snap-record-delete-confirm"]').click()
    await p.waitForTimeout(1500)
  }
  await ctx.close()

  // ===== 5. 教师端：漏题提示不误报 =====
  const tctx = await browser.newContext({ viewport: { width: 1200, height: 900 } })
  const tp = await tctx.newPage()
  check("教师登录", await login(tp, TEACHER))
  await tp.goto(`${BASE}/exams/${EXAM_ID}/questions`, { waitUntil: "commit", timeout: 60000 })
  await tp.waitForTimeout(6000)
  const warn = await tp.locator('[data-testid="missing-questions-warning"]').count()
  const items = await tp.locator('[data-testid^="recognition-item-"]').count()
  check("漏题提示不误报", warn === 0 || items === 0, `识别项 ${items}，警告 ${warn}`)
  await tctx.close()
  await browser.close()

  const failed = results.filter((r) => !r.ok)
  console.log(`\n=== 结果：${results.length - failed.length}/${results.length} 通过 ===\n`)
  process.exit(failed.length ? 1 : 0)
}

main()
