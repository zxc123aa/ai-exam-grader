/**
 * 报告问题复测：#10 同卷连批两次给分必须一致；#5 全流程不卡死。
 * node scripts/repro-consistency.mjs
 */
import { createRequire } from "node:module"

const require = createRequire(
  new URL("../frontend/package.json", import.meta.url),
)
const { chromium } = require("playwright")

const BASE = (process.env.SMOKE_BASE_URL || "https://app.dianfandig.com").replace(/\/$/, "")
const PHOTO = process.env.SMOKE_PHOTO || "/mnt/d/Songtan/ai-exam-grader/materials/内测小学数学/张一1.jpg"

async function login(p) {
  await p.goto(`${BASE}/login`, { waitUntil: "commit", timeout: 60000 })
  await p.waitForSelector('input[type="email"]', { timeout: 60000 })
  await p.fill('input[type="email"]', process.env.SMOKE_STUDENT_EMAIL || "zhangyi@example.com")
  await p.fill('input[type="password"]', process.env.SMOKE_STUDENT_PASSWORD || "student123")
  await p.click('button[type="submit"]')
  await p.waitForTimeout(6000)
}

async function gradeOnce(p, tag) {
  await p.goto(`${BASE}/my/snap`, { waitUntil: "commit", timeout: 60000 })
  await p.waitForSelector('[data-testid="tab-grade"]', { timeout: 30000 })
  await p.click('[data-testid="tab-grade"]')
  await p.locator('[data-testid="snap-upload-input"]').setInputFiles(PHOTO)
  await p.waitForTimeout(800)
  await p.click('[data-testid="snap-submit"]')
  const t0 = Date.now()
  await p.waitForSelector('[data-testid="snap-grade-stream-result"]', { timeout: 420000 })
  const cardsAt = Math.round((Date.now() - t0) / 1000)
  await p.waitForFunction(
    () => !document.body.innerText.includes("批改中"),
    null,
    { timeout: 300000 },
  )
  const totalS = Math.round((Date.now() - t0) / 1000)
  const text = await p.locator('[data-testid="snap-grade-stream-result"]').innerText()
  // 抽出每题得分：「第 N 题 … score / max 分」
  const scores = []
  for (const m of text.matchAll(/第 (\d+) 题[\s\S]*?(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?) 分/g)) {
    scores.push({ q: Number(m[1]), score: m[2], max: m[3] })
  }
  console.log(`${tag}: ${scores.length} 题判完, 识别 ${cardsAt}s, 全部 ${totalS}s`)
  return { scores, text, totalS }
}

const browser = await chromium.launch({
  executablePath: "/home/st/.cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell",
})
const p = await (await browser.newContext({ viewport: { width: 900, height: 1000 } })).newPage()
p.on("pageerror", (e) => console.log("PAGEERROR:", e.message.slice(0, 150)))
await login(p)

const run1 = await gradeOnce(p, "第 1 次")
const run2 = await gradeOnce(p, "第 2 次")

// #5 卡死检查
console.log(run1.totalS < 300 && run2.totalS < 300 ? "PASS  #5 全流程不卡死" : "FAIL  #5 仍有卡死")

// #10 一致性：同题同卷两次给分应一致
const by1 = new Map(run1.scores.map((s) => [s.q, s.score]))
const by2 = new Map(run2.scores.map((s) => [s.q, s.score]))
const diffs = []
for (const [q, s1] of by1) {
  const s2 = by2.get(q)
  if (s2 !== undefined && s1 !== s2) diffs.push(`第${q}题 ${s1}≠${s2}`)
}
console.log(
  diffs.length === 0
    ? `PASS  #10 同卷两次给分一致（${by1.size} 题）`
    : `FAIL  #10 给分不一致 ${diffs.length} 题: ${diffs.slice(0, 6).join("、")}`,
)

// #12 更正笔迹粗查：学生作答字段不应出现明显的标准答案式完整解答
const answered = (run1.text.match(/你的作答/g) || []).length
console.log(`INFO  作答字段 ${answered} 条（人工抽查识别文本是否原样）`)
await browser.close()
