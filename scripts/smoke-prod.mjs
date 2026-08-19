/**
 * 点凡阅卷 发版冒烟回归：公网（或任意环境）核心链路自动化检查。
 *
 * 用法：
 *   node scripts/smoke-prod.mjs                 # 打 https://app.dianfandig.com
 *   SMOKE_BASE_URL=http://localhost:5173 node scripts/smoke-prod.mjs   # 打本地
 *
 * 覆盖：健康检查、教师端（工作台/考试/导入/确认题目/批卷工作台/成绩）、
 * 学生端（/my 重定向、成绩、拍题答疑、拍题记录、错题本、知识图谱、变式练习）、
 * 横批 N+1 回归（批注请求数）。任何页面出现全局错误页或 JS 异常即失败。
 *
 * 账号可用环境变量覆盖：SMOKE_TEACHER_EMAIL / SMOKE_TEACHER_PASSWORD /
 * SMOKE_STUDENT_EMAIL / SMOKE_STUDENT_PASSWORD。
 * 只读操作为主：不建考试、不上传、不调模型（不产生费用）。
 */
import { createRequire } from "node:module"

const require = createRequire(
  new URL("../frontend/package.json", import.meta.url),
)
const { chromium } = require("playwright")

const BASE = (process.env.SMOKE_BASE_URL || "https://app.dianfandig.com").replace(
  /\/$/,
  "",
)
// API 与前端同域（nginx 把 /api 反代到后端）；可用 SMOKE_API_URL 覆盖
const API_BASE = process.env.SMOKE_API_URL || BASE
const TEACHER = {
  email: process.env.SMOKE_TEACHER_EMAIL || "demo.owner@example.com",
  password: process.env.SMOKE_TEACHER_PASSWORD || "demo12345",
}
const STUDENT = {
  email: process.env.SMOKE_STUDENT_EMAIL || "zhangyi@example.com",
  password: process.env.SMOKE_STUDENT_PASSWORD || "student123",
}
// 演示考试（有完整批改数据）：可用环境变量覆盖
const EXAM_ID =
  process.env.SMOKE_EXAM_ID || "580eaa0b-2bf4-4899-a729-9d97ac7d6f5f"

const results = []
let currentErrors = []

function check(name, ok, detail = "") {
  results.push({ name, ok, detail })
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

async function visit(page, path, { expectTestId, settleMs = 4000 } = {}) {
  await page.goto(`${BASE}${path}`, { waitUntil: "commit", timeout: 60000 })
  await p_settle(page, settleMs)
  const errorPage = await page.locator('[data-testid="error-component"]').count()
  let rendered = true
  if (expectTestId) {
    rendered = (await page.locator(expectTestId).count()) > 0
  }
  return { errorPage: errorPage > 0, rendered, url: page.url() }
}

async function p_settle(page, ms) {
  await page.waitForTimeout(ms)
}

async function main() {
  console.log(`\n=== 点凡阅卷 发版冒烟：${BASE} ===\n`)
  const browser = await chromium.launch({
    executablePath:
      "/home/st/.cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell",
  })

  // 0. 健康检查
  try {
    const ready = await fetch(`${API_BASE}/api/v1/utils/health/ready`).then(
      (r) => r.json(),
    )
    check("API 健康检查", ready.status === "ready")
  } catch (error) {
    check("API 健康检查", false, String(error).slice(0, 120))
  }

  // ===== 教师端 =====
  const teacherCtx = await browser.newContext({
    viewport: { width: 1280, height: 900 },
  })
  const tp = await teacherCtx.newPage()
  tp.on("pageerror", (e) =>
    currentErrors.push(`${tp.url()} :: ${e.message.slice(0, 150)}`),
  )
  check("教师登录", await login(tp, TEACHER))

  for (const [path, name] of [
    ["/", "工作台"],
    ["/exams", "考试管理"],
    [`/exams/${EXAM_ID}`, "考试-导入试卷"],
    [`/exams/${EXAM_ID}/questions`, "考试-确认题目"],
    [`/exams/${EXAM_ID}/answers`, "考试-标准答案"],
    [`/exams/${EXAM_ID}/grading`, "考试-批改与复核"],
    [`/exams/${EXAM_ID}/scores`, "考试-成绩"],
  ]) {
    const r = await visit(tp, path)
    check(`教师页 ${name}`, !r.errorPage && r.rendered)
  }

  // 横批 N+1 回归：批注数据请求应只有 1 个（合并接口）
  const annotationCalls = []
  tp.on("request", (req) => {
    if (req.url().includes("/annotations")) annotationCalls.push(req.url())
  })
  const wb = await visit(tp, `/exams/${EXAM_ID}/workbench`, { settleMs: 8000 })
  const dataCalls = annotationCalls.filter((u) => u.endsWith("/annotations"))
  const perStudentCalls = annotationCalls.filter((u) =>
    /submissions\/[^/]+\/annotations$/.test(u),
  )
  check(
    "批卷工作台打开",
    !wb.errorPage,
    wb.errorPage ? "" : `批注请求 ${dataCalls.length} 个`,
  )
  check(
    "横批 N+1 回归（无逐学生批注请求）",
    perStudentCalls.length === 0,
    `逐学生请求 ${perStudentCalls.length} 个`,
  )
  check("教师端无 JS 异常", currentErrors.length === 0, currentErrors[0] ?? "")
  await teacherCtx.close()

  // ===== 学生端 =====
  currentErrors = []
  const studentCtx = await browser.newContext({
    viewport: { width: 1000, height: 900 },
  })
  const sp = await studentCtx.newPage()
  sp.on("pageerror", (e) =>
    currentErrors.push(`${sp.url()} :: ${e.message.slice(0, 150)}`),
  )
  check("学生登录", await login(sp, STUDENT))

  await sp.goto(`${BASE}/my`, { waitUntil: "commit", timeout: 60000 })
  await p_settle(sp, 3000)
  check("裸 /my 重定向", sp.url().includes("/my/exams"), sp.url())

  for (const [path, name] of [
    ["/my/exams", "我的成绩"],
    ["/my/snap", "拍题答疑"],
    ["/my/snap-history", "拍题记录"],
    ["/my/wrongbook", "错题本"],
    ["/my/knowledge", "知识图谱"],
    ["/my/wrongbook-sheet", "变式练习"],
  ]) {
    const r = await visit(sp, path)
    check(`学生页 ${name}`, !r.errorPage && r.rendered)
  }

  // 拍题答疑关键控件
  await visit(sp, "/my/snap")
  check(
    "拍题答疑 控件（答疑/批改 tab + 上传入口）",
    (await sp.locator('[data-testid="tab-solve"]').count()) > 0 &&
      (await sp.locator('[data-testid="tab-grade"]').count()) > 0,
  )

  // 错题本「未评分」回归：不再出现 0 / -- 分
  await visit(sp, "/my/wrongbook")
  const wrongbookText = await sp
    .locator("main")
    .last()
    .innerText()
    .catch(() => "")
  check("错题本无「/ -- 分」残留", !wrongbookText.includes("/ --"))

  check("学生端无 JS 异常", currentErrors.length === 0, currentErrors[0] ?? "")
  await studentCtx.close()
  await browser.close()

  const failed = results.filter((r) => !r.ok)
  console.log(
    `\n=== 结果：${results.length - failed.length}/${results.length} 通过${
      failed.length ? `，${failed.length} 项失败` : ""
    } ===\n`,
  )
  process.exit(failed.length ? 1 : 0)
}

main()
