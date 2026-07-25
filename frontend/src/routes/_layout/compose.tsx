import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import {
  Check,
  Loader2,
  Minus,
  Plus,
  Settings2,
  Sparkles,
  Wand2,
  Zap,
} from "lucide-react"
import { useMemo, useState } from "react"

import { ExamsService, type QuestionBankEntryPublic } from "@/client"
import { Chip } from "@/components/Common/Chip"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHead } from "@/components/Common/PageHead"
import { Tag } from "@/components/Common/Tag"
import { Button } from "@/components/ui/button"
import { useCurrentExam } from "@/hooks/useCurrentExam"
import useCustomToast from "@/hooks/useCustomToast"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout/compose")({
  component: ComposePage,
  head: () => ({ meta: [{ title: "重新组卷 - 点凡阅卷" }] }),
})

const TYPE_LABELS: Record<string, string> = {
  single_choice: "单选题",
  multiple_choice: "多选题",
  true_false: "判断题",
  fill_blank: "填空题",
  calculation: "计算题",
  proof: "证明题",
  short_answer: "简答题",
  essay: "论述题",
}

const typeKey = (questionType: string | null) => questionType ?? "其他"
const typeLabel = (questionType: string | null) =>
  questionType ? (TYPE_LABELS[questionType] ?? questionType) : "其他"

/** 预计时长：选择 3 分钟/题、填空 4、解答 12，默认 8。 */
function minutesFor(questionType: string | null) {
  const value = questionType ?? ""
  if (
    value.includes("选择") ||
    ["single_choice", "multiple_choice", "true_false"].includes(value)
  )
    return 3
  if (value.includes("填空") || value === "fill_blank") return 4
  if (value.includes("解答")) return 12
  return 8
}

const DEFAULT_COUNT = 3
const DEFAULT_SCORE = 5

/** client 生成的可选字段归一化为 null，便于页面逻辑判空。 */
type BankEntry = Omit<
  QuestionBankEntryPublic,
  "question_type" | "knowledge_point" | "difficulty" | "max_score"
> & {
  question_type: string | null
  knowledge_point: string | null
  difficulty: number | null
  max_score: number | null
}

function ComposePage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { currentExamId } = useCurrentExam()
  const [selectedKps, setSelectedKps] = useState<Set<string>>(new Set())
  const [difficulty, setDifficulty] = useState(3)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [weakFirst, setWeakFirst] = useState(false)

  const bank = useQuery({
    queryKey: ["question-bank"],
    queryFn: () => ExamsService.readQuestionBank(),
  })
  const summary = useQuery({
    queryKey: ["exam-scores-summary", currentExamId],
    queryFn: () =>
      ExamsService.readExamScoresSummary({ examId: currentExamId! }),
    enabled: Boolean(currentExamId),
  })

  const entries: BankEntry[] = useMemo(
    () =>
      (bank.data?.data ?? []).map((entry) => ({
        ...entry,
        question_type: entry.question_type ?? null,
        knowledge_point: entry.knowledge_point ?? null,
        difficulty: entry.difficulty ?? null,
        max_score: entry.max_score ?? null,
      })),
    [bank.data],
  )

  const knowledgePoints = useMemo(
    () =>
      [
        ...new Set(
          entries
            .map((entry) => entry.knowledge_point)
            .filter((value): value is string => Boolean(value)),
        ),
      ].sort((a, b) => a.localeCompare(b, "zh-CN")),
    [entries],
  )

  /** 当前考试各题得分率 <60% 的题对应的知识点 = 薄弱点。 */
  const weakKps = useMemo(() => {
    const result = new Set<string>()
    if (!currentExamId || !summary.data) return result
    const totals = new Map<string, { score: number; max: number }>()
    for (const row of summary.data.data) {
      for (const question of row.questions ?? []) {
        if (question.score == null || !question.max_score) continue
        const current = totals.get(question.label) ?? { score: 0, max: 0 }
        current.score += question.score
        current.max += question.max_score
        totals.set(question.label, current)
      }
    }
    const kpByLabel = new Map<string, string>()
    for (const entry of entries) {
      if (entry.exam_id === currentExamId && entry.knowledge_point)
        kpByLabel.set(entry.label, entry.knowledge_point)
    }
    for (const [label, total] of totals) {
      if (total.max > 0 && total.score / total.max < 0.6) {
        const kp = kpByLabel.get(label)
        if (kp) result.add(kp)
      }
    }
    return result
  }, [currentExamId, summary.data, entries])

  const bankTypes = useMemo(
    () => [...new Set(entries.map((entry) => typeKey(entry.question_type)))],
    [entries],
  )

  const countFor = (type: string) => counts[type] ?? DEFAULT_COUNT

  /** 依据配置选题：勾选的知识点 ∪ 空知识点；难度差 ≤2；薄弱优先。 */
  const groups = useMemo(() => {
    const pool = entries.filter(
      (entry) =>
        (entry.knowledge_point === null ||
          selectedKps.has(entry.knowledge_point)) &&
        (entry.difficulty === null ||
          Math.abs(entry.difficulty - difficulty) <= 2),
    )
    const ordered = weakFirst
      ? [
          ...pool.filter(
            (entry) =>
              entry.knowledge_point && weakKps.has(entry.knowledge_point),
          ),
          ...pool.filter(
            (entry) =>
              !entry.knowledge_point || !weakKps.has(entry.knowledge_point),
          ),
        ]
      : pool
    return bankTypes
      .map((type) => ({
        type,
        questions: ordered
          .filter((entry) => typeKey(entry.question_type) === type)
          .slice(0, counts[type] ?? DEFAULT_COUNT),
      }))
      .filter((group) => group.questions.length > 0)
  }, [entries, selectedKps, difficulty, weakFirst, weakKps, bankTypes, counts])

  const picked = groups.flatMap((group) => group.questions)
  const totalScore = picked.reduce(
    (sum, entry) => sum + (entry.max_score ?? DEFAULT_SCORE),
    0,
  )
  const totalMinutes = picked.reduce(
    (sum, entry) => sum + minutesFor(entry.question_type),
    0,
  )

  const toggleKp = (kp: string) =>
    setSelectedKps((current) => {
      const next = new Set(current)
      if (next.has(kp)) next.delete(kp)
      else next.add(kp)
      return next
    })

  const generate = useMutation({
    mutationFn: () =>
      ExamsService.composeExam({
        requestBody: {
          title: `巩固组卷 ${new Date().toLocaleString("zh-CN", {
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
          })}`,
          question_ids: picked.map((entry) => entry.question_id),
        },
      }),
    onSuccess: (exam) => {
      showSuccessToast(`试卷「${exam.title}」已生成`)
      queryClient.invalidateQueries({ queryKey: ["exams"] })
      navigate({ to: "/exams/$examId", params: { examId: exam.id } })
    },
    onError: (error) =>
      showErrorToast(error instanceof Error ? error.message : "生成失败"),
  })

  if (bank.isLoading) {
    return (
      <div className="flex min-h-48 items-center justify-center gap-2 text-muted-foreground text-sm">
        <Loader2 className="animate-spin" />
        正在加载题库…
      </div>
    )
  }

  if (!entries.length) {
    return (
      <div className="flex flex-col gap-6">
        <PageHead
          title="重新组卷"
          subtitle="基于班级薄弱知识点智能组卷，练测闭环"
        />
        <EmptyState
          icon={Wand2}
          title="题库还是空的"
          description="先在考试中确认识别题目并标注知识点，确认后的题目会自动进入题库"
        />
      </div>
    )
  }

  let questionNo = 0

  return (
    <div className="flex flex-col gap-6">
      <PageHead
        title="重新组卷"
        subtitle="基于班级薄弱知识点智能组卷，练测闭环"
      />
      <div className="grid items-start gap-6 lg:grid-cols-[360px_minmax(0,1fr)]">
        {/* 左：配置面板 */}
        <section className="grid gap-5 rounded-2xl border bg-card p-5 shadow-card">
          <h3 className="flex items-center gap-2 font-semibold text-sm">
            <Settings2 className="size-4" />
            组卷配置
          </h3>

          <div className="grid gap-2">
            <div className="font-medium text-sm">
              知识点范围
              {weakKps.size > 0 && (
                <span className="ml-1 text-muted-foreground text-xs">
                  （红色为本次薄弱点）
                </span>
              )}
            </div>
            {knowledgePoints.length ? (
              <div className="flex flex-wrap gap-2">
                {knowledgePoints.map((kp) => {
                  const weak = weakKps.has(kp)
                  const active = selectedKps.has(kp)
                  return (
                    <Chip
                      key={kp}
                      active={active}
                      onClick={() => toggleKp(kp)}
                      className={cn(
                        "inline-flex items-center gap-1",
                        weak &&
                          !active &&
                          "border border-red-400 text-red-600 dark:text-red-400",
                      )}
                    >
                      {active && <Check className="size-3" />}
                      {kp}
                    </Chip>
                  )
                })}
              </div>
            ) : (
              <p className="text-muted-foreground text-xs">
                题库题目还没有标注知识点，将使用全部题目组卷
              </p>
            )}
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between font-medium text-sm">
              整体难度
              <span className="text-amber-500">
                {"★".repeat(difficulty)}
                <span className="text-muted-foreground/40">
                  {"★".repeat(5 - difficulty)}
                </span>
              </span>
            </div>
            <input
              type="range"
              min={1}
              max={5}
              value={difficulty}
              onChange={(event) => setDifficulty(Number(event.target.value))}
              className="w-full accent-primary"
              aria-label="整体难度"
            />
            <div className="flex justify-between text-muted-foreground text-xs">
              <span>基础</span>
              <span>适中</span>
              <span>拔高</span>
            </div>
          </div>

          <div className="grid gap-2">
            <div className="font-medium text-sm">题型数量</div>
            {bankTypes.map((type) => (
              <div key={type} className="flex items-center justify-between">
                <Tag variant="indigo">{typeLabel(type)}</Tag>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="icon"
                    className="size-7"
                    aria-label={`减少${typeLabel(type)}`}
                    disabled={countFor(type) <= 0}
                    onClick={() =>
                      setCounts((current) => ({
                        ...current,
                        [type]: Math.max(0, countFor(type) - 1),
                      }))
                    }
                  >
                    <Minus className="size-3" />
                  </Button>
                  <span className="w-6 text-center font-medium text-sm tabular-nums">
                    {countFor(type)}
                  </span>
                  <Button
                    variant="outline"
                    size="icon"
                    className="size-7"
                    aria-label={`增加${typeLabel(type)}`}
                    disabled={countFor(type) >= 10}
                    onClick={() =>
                      setCounts((current) => ({
                        ...current,
                        [type]: Math.min(10, countFor(type) + 1),
                      }))
                    }
                  >
                    <Plus className="size-3" />
                  </Button>
                </div>
              </div>
            ))}
          </div>

          <div className="grid gap-1">
            <button
              type="button"
              className="flex items-center justify-between"
              onClick={() => setWeakFirst((current) => !current)}
              aria-pressed={weakFirst}
            >
              <span className="flex items-center gap-1.5 font-medium text-sm">
                <Zap className="size-4 text-amber-500" />
                优先选薄弱知识点题
              </span>
              <span
                className={cn(
                  "flex h-5 w-9 items-center rounded-full p-0.5 transition-colors",
                  weakFirst ? "bg-primary justify-end" : "bg-muted",
                )}
              >
                <span className="size-4 rounded-full bg-white shadow" />
              </span>
            </button>
            <p className="text-muted-foreground text-xs">
              开启后当前考试得分率低于 60% 的知识点题目排在前面
            </p>
          </div>

          <div className="grid gap-1.5 border-t pt-4 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">预计题数</span>
              <b>{picked.length} 题</b>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">试卷总分</span>
              <b>{totalScore} 分</b>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">预计时长</span>
              <b>约 {totalMinutes} 分钟</b>
            </div>
          </div>

          <Button
            className="w-full bg-gradient-primary text-white hover:opacity-90"
            disabled={!picked.length || generate.isPending}
            onClick={() => generate.mutate()}
          >
            {generate.isPending ? (
              <Loader2 className="animate-spin" />
            ) : (
              <Sparkles />
            )}
            生成试卷
          </Button>
        </section>

        {/* 右：试卷结构预览 */}
        {picked.length ? (
          <section className="overflow-hidden rounded-2xl border bg-card shadow-card">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b px-5 py-4">
              <h3 className="font-semibold text-sm">试卷结构预览</h3>
              <span className="text-muted-foreground text-xs">
                共 {picked.length} 题 · 总分 {totalScore} 分 · 约 {totalMinutes}{" "}
                分钟
              </span>
            </div>
            {groups.map((group) => (
              <div key={group.type} className="border-b last:border-b-0">
                <div className="flex items-center gap-2 bg-secondary/40 px-5 py-2.5">
                  <Tag variant="indigo">{typeLabel(group.type)}</Tag>
                  <span className="text-muted-foreground text-xs">
                    {group.questions.length} 题
                  </span>
                </div>
                {group.questions.map((entry) => {
                  questionNo += 1
                  return (
                    <PreviewRow
                      key={entry.question_id}
                      no={questionNo}
                      entry={entry}
                      weak={
                        entry.knowledge_point
                          ? weakKps.has(entry.knowledge_point)
                          : false
                      }
                    />
                  )
                })}
              </div>
            ))}
            <div className="flex items-center justify-between px-5 py-3 text-sm">
              <span className="text-muted-foreground">合计</span>
              <b>{totalScore} 分</b>
            </div>
          </section>
        ) : (
          <EmptyState
            icon={Wand2}
            title="当前配置下没有匹配的题目"
            description="请勾选至少一个知识点，或调整难度范围与题型数量"
            className="bg-card shadow-card"
          />
        )}
      </div>
    </div>
  )
}

function PreviewRow({
  no,
  entry,
  weak,
}: {
  no: number
  entry: BankEntry
  weak: boolean
}) {
  return (
    <div className="flex items-center gap-3 border-t px-5 py-3 first:border-t-0">
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 font-medium text-primary text-xs">
        {no}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium text-sm">
          {entry.question_text}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-muted-foreground text-xs">
          <span className="truncate">{entry.exam_title}</span>
          {entry.knowledge_point && (
            <span className={weak ? "font-medium text-red-500" : undefined}>
              {entry.knowledge_point}
              {weak ? "（薄弱）" : ""}
            </span>
          )}
          {entry.difficulty && (
            <span className="text-amber-500">
              {"★".repeat(entry.difficulty)}
            </span>
          )}
        </div>
      </div>
      <span className="shrink-0 font-medium text-sm tabular-nums">
        {entry.max_score ?? DEFAULT_SCORE} 分
      </span>
    </div>
  )
}
