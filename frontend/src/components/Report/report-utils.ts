/**
 * 报告页（教师改卷报告 / 学生个人成绩报告）共用的逐题视图模型与文案工具。
 * 两页结构同构：教师页由成绩 summary 合并而来，学生页由我的成绩报告接口而来。
 */

export type ReportQuestionItem = {
  label: string
  score: number | null
  maxScore: number | null
  /** final = 教师复核后的最终分（师改），其余为建议分 */
  source?: string | null
  /** 评语 / 正确思路（comment || suggested_comment） */
  comment?: string | null
  /** 教师侧取图：有 submissionId + annotationId 时按题区实时裁切 */
  submissionId?: string | null
  annotationId?: string | null
  /** 学生侧取图：错题本条目自带留存的答题图，不需要考试权限 */
  entryId?: string | null
  hasImage?: boolean
}

export function formatScore(value: number | null | undefined): string {
  if (value == null) return "--"
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

/** 得分率 0-100；缺分或满分为 0 时返回 null。 */
export function scoreRate(question: {
  score: number | null
  maxScore: number | null
}): number | null {
  if (question.score == null || !question.maxScore) return null
  return Math.round((question.score / question.maxScore) * 100)
}

export function rateColor(rate: number | null): string {
  if (rate == null) return ""
  if (rate >= 80) return "text-emerald-600 dark:text-emerald-400"
  if (rate >= 40) return "text-amber-600 dark:text-amber-400"
  return "text-red-600 dark:text-red-400"
}

export function sortQuestionsByLabel<T extends { label: string }>(
  questions: T[],
): T[] {
  return [...questions].sort((a, b) =>
    a.label.localeCompare(b.label, "zh-Hans-CN", { numeric: true }),
  )
}

type RatedQuestion<T> = { question: T; rate: number }

function ratedQuestions<
  T extends { score: number | null; maxScore: number | null },
>(questions: T[]): RatedQuestion<T>[] {
  return questions
    .map((question) => ({ question, rate: scoreRate(question) }))
    .filter((entry): entry is RatedQuestion<T> => entry.rate != null)
}

/** 主要失分题：得分率不足 100% 的题按得分率升序取前 limit 题。 */
function mainLostQuestions<
  T extends { score: number | null; maxScore: number | null },
>(questions: T[], limit = 3): RatedQuestion<T>[] {
  return ratedQuestions(questions)
    .filter((entry) => entry.rate < 100)
    .sort((a, b) => a.rate - b.rate)
    .slice(0, limit)
}

/**
 * 总分下的摘要行：「主要失分：第 x、y、z 题 · 最需要加强：{知识点|题号}」。
 * 全部满分或暂无出分题时返回 null（不展示）。
 */
export function buildSummaryLine<
  T extends { label: string; score: number | null; maxScore: number | null },
>(questions: T[], knowledgeByLabel?: Map<string, string>): string | null {
  const lost = mainLostQuestions(questions)
  if (lost.length === 0) return null
  const worst = lost[0]
  const focus =
    knowledgeByLabel?.get(worst.question.label) ?? worst.question.label
  return `主要失分：${lost.map((entry) => entry.question.label).join("、")} · 最需要加强：${focus}`
}

/**
 * 具体化学习建议：引用实际错题号与知识点（无知识点时只用题号），
 * 不用「进一步巩固基础知识」这类空泛模板。
 */
export function buildAdvice<
  T extends { label: string; score: number | null; maxScore: number | null },
>(questions: T[], knowledgeByLabel?: Map<string, string>): string {
  const rated = ratedQuestions(questions)
  if (rated.length === 0) {
    return "逐题得分数据还不完整，完成全部批改与复核后会给出针对性的学习建议。"
  }
  const low = rated
    .filter((entry) => entry.rate < 60)
    .sort((a, b) => a.rate - b.rate)
    .slice(0, 3)
  if (low.length === 0) {
    return "各题得分率均在 60% 以上，基础掌握扎实。可以保持当前节奏，适当挑战综合题与压轴题。"
  }
  const labels = low.map((entry) => entry.question.label).join("、")
  const knowledgePoints = [
    ...new Set(
      low
        .map((entry) => knowledgeByLabel?.get(entry.question.label))
        .filter((kp): kp is string => Boolean(kp)),
    ),
  ]
  if (knowledgePoints.length > 0) {
    const kpText = knowledgePoints.join("、")
    return `${labels}失分较多（${kpText}）。建议先复习${kpText}的基础题型，再完成同类练习 5 题。`
  }
  return `${labels}失分较多。建议先复习这些题对应的基础题型，再完成同类练习 5 题。`
}
