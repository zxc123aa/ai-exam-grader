import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import {
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  FileSearch,
  Loader2,
  Save,
  ScanSearch,
  Upload,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { z } from "zod"

import { ExamsService } from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { MathText } from "@/components/Common/MathText"
import { Tag } from "@/components/Common/Tag"
import { ImportCenterDialog } from "@/components/Exams/ImportCenterDialog"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { cn } from "@/lib/utils"
import { workflowApi } from "@/lib/workflow-api"

export const Route = createFileRoute("/_layout/exams_/$examId/questions")({
  component: QuestionWorkspace,
  validateSearch: z.object({ runId: z.string().optional() }),
  head: () => ({ meta: [{ title: "确认题目 - 点凡阅卷" }] }),
})

type WorkflowStatus =
  | "queued"
  | "running"
  | "completed"
  | "completed_with_errors"
  | "failed"

type RecognitionRun = {
  id: string
  status: WorkflowStatus
  engine: string
  provider: string
  model: string
  document_ids: string[]
  timing: Record<string, number>
  item_count: number
  error_message: string | null
  confirmed_at: string | null
}

type RecognitionItem = {
  id: string
  question_key: string
  label: string
  question_text: string
  student_answer_text: string | null
  question_type: string | null
  knowledge_point: string | null
  difficulty: number | null
  confidence: number | null
  notes: string | null
  region_ids: string[]
  region_snapshots: Record<string, unknown>[]
  status: "draft" | "confirmed" | "excluded"
}

const questionTypes = [
  ["single_choice", "单选题"],
  ["multiple_choice", "多选题"],
  ["true_false", "判断题"],
  ["fill_blank", "填空题"],
  ["calculation", "计算题"],
  ["proof", "证明题"],
  ["short_answer", "简答题"],
  ["essay", "论述题"],
  ["未知", "未知"],
]

function statusBadge(status: WorkflowStatus, confirmed: boolean) {
  if (confirmed) return <Tag variant="mint">已确认</Tag>
  if (status === "running" || status === "queued")
    return <Tag variant="sky">识别中</Tag>
  if (status === "failed") return <Tag variant="red">失败</Tag>
  if (status === "completed_with_errors")
    return <Tag variant="amber">待处理异常</Tag>
  return <Tag variant="indigo">待确认</Tag>
}

function formatMs(value?: number) {
  if (value === undefined || value === null) return "—"
  return value >= 1000 ? `${(value / 1000).toFixed(2)} 秒` : `${value} 毫秒`
}

function questionTypeLabel(value: string | null) {
  return questionTypes.find(([key]) => key === value)?.[1] ?? "未知"
}

/**
 * 漏题校验：按题号前缀分组（「三、」「填空」等各自从 1 计数），
 * 组内题号应连续；中间断号说明可能有题没识别出来，提醒老师核对原卷。
 */
function findMissingQuestions(items: RecognitionItem[]): string[] {
  const groups = new Map<string, Set<number>>()
  for (const item of items) {
    // 已排除的题也算入序列：它是被识别出来、老师手动排除的，不算漏识别
    const match =
      item.question_key.match(/^(\D*)(\d+)/) ?? item.label.match(/^(\D*)(\d+)/)
    if (!match) continue
    const [, prefix, num] = match
    const group = groups.get(prefix) ?? new Set<number>()
    group.add(Number(num))
    groups.set(prefix, group)
  }
  const missing: string[] = []
  for (const [prefix, nums] of groups) {
    if (nums.size < 3) continue // 题太少不报，避免误报
    const sorted = [...nums].sort((a, b) => a - b)
    for (let n = sorted[0]; n <= sorted[sorted.length - 1]; n++) {
      if (!nums.has(n)) missing.push(`${prefix || ""}第 ${n} 题`)
    }
  }
  return missing
}

function QuestionItemRow({
  item,
  locked,
  error,
  onChange,
}: {
  item: RecognitionItem
  locked: boolean
  error?: string
  onChange: (next: RecognitionItem) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const excluded = item.status === "excluded"
  const regionCount = item.region_ids.length || item.region_snapshots.length

  return (
    <div
      className={error ? "border-l-2 border-l-destructive" : ""}
      data-testid={`recognition-item-${item.id}`}
    >
      <div className="flex items-center gap-3 px-4 py-3 text-sm hover:bg-muted/50">
        <Checkbox
          checked={!excluded}
          disabled={locked}
          aria-label={`保留${item.label}`}
          onCheckedChange={(checked) =>
            onChange({
              ...item,
              status: checked ? "draft" : "excluded",
            })
          }
        />
        <button
          type="button"
          aria-expanded={expanded}
          className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 text-left"
          onClick={() => setExpanded((current) => !current)}
        >
          <span className="max-w-56 shrink-0 truncate whitespace-nowrap font-medium">
            {item.label}
          </span>
          <span
            className="min-w-0 flex-1 truncate text-muted-foreground"
            title={item.question_text}
          >
            {item.question_text}
          </span>
          <Tag variant="indigo" className="shrink-0">
            {questionTypeLabel(item.question_type)}
          </Tag>
          {excluded && <Tag variant="red">已排除</Tag>}
          {item.confidence !== null && item.confidence < 0.8 && (
            <Tag variant="amber" className="shrink-0">
              请复核
            </Tag>
          )}
          {error && (
            <span className="shrink-0 text-xs text-destructive">{error}</span>
          )}
          <ChevronDown
            className={cn(
              "size-4 shrink-0 text-muted-foreground transition-transform",
              expanded && "rotate-180",
            )}
          />
        </button>
      </div>

      {expanded && (
        <div className="grid gap-4 border-t bg-muted/20 px-4 py-5">
          <div className="grid gap-3 md:grid-cols-[140px_180px_minmax(0,1fr)]">
            <div className="grid gap-2">
              <Label>题目标识</Label>
              <Input
                value={item.question_key}
                disabled={locked || excluded}
                onChange={(event) =>
                  onChange({ ...item, question_key: event.target.value })
                }
              />
            </div>
            <div className="grid gap-2">
              <Label>题型</Label>
              <Select
                value={item.question_type ?? "未知"}
                disabled={locked || excluded}
                onValueChange={(value) =>
                  onChange({ ...item, question_type: value })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {questionTypes.map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label>显示名称</Label>
              <Input
                value={item.label}
                disabled={locked || excluded}
                onChange={(event) =>
                  onChange({ ...item, label: event.target.value })
                }
              />
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px]">
            <div className="grid gap-2">
              <Label>知识点</Label>
              <Input
                value={item.knowledge_point ?? ""}
                placeholder="如：电场、光学、力学"
                disabled={locked || excluded}
                onChange={(event) =>
                  onChange({
                    ...item,
                    knowledge_point: event.target.value || null,
                  })
                }
              />
            </div>
            <div className="grid gap-2">
              <Label>难度</Label>
              <Select
                value={item.difficulty ? String(item.difficulty) : "none"}
                disabled={locked || excluded}
                onValueChange={(value) =>
                  onChange({
                    ...item,
                    difficulty: value === "none" ? null : Number(value),
                  })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">未标注</SelectItem>
                  {[1, 2, 3, 4, 5].map((value) => (
                    <SelectItem key={value} value={String(value)}>
                      {"★".repeat(value)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid gap-2">
            <Label>印刷题目与选项</Label>
            {item.question_text && (
              <div className="rounded-md border bg-muted/30 px-4 py-3">
                <MathText
                  text={item.question_text}
                  className="whitespace-pre-wrap text-sm leading-7"
                />
              </div>
            )}
            <textarea
              className="border-input min-h-36 w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={item.question_text}
              disabled={locked || excluded}
              onChange={(event) =>
                onChange({ ...item, question_text: event.target.value })
              }
            />
          </div>

          {item.student_answer_text && (
            <div className="grid gap-2 border-l-2 border-amber-500 bg-amber-50/50 px-4 py-3 dark:bg-amber-950/15">
              <div className="text-xs font-medium text-amber-800 dark:text-amber-300">
                卷面中的考生作答
              </div>
              <MathText
                text={item.student_answer_text}
                className="whitespace-pre-wrap text-sm leading-7"
              />
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <span>{regionCount} 个识别区域</span>
            {item.confidence !== null && (
              <span className="inline-flex items-center gap-1">
                {item.confidence < 0.8
                  ? "题目内容可能不完整，请对照原卷确认"
                  : "题目内容已完成初步检查"}
              </span>
            )}
            {item.notes && <span>{item.notes}</span>}
          </div>
        </div>
      )}
    </div>
  )
}

function QuestionWorkspace() {
  const { examId } = Route.useParams()
  const { runId: requestedRunId } = Route.useSearch()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([])
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<Record<string, RecognitionItem>>({})
  const [dirtyIds, setDirtyIds] = useState<Set<string>>(new Set())
  const [saveErrors, setSaveErrors] = useState<Record<string, string>>({})
  const files = useQuery({
    queryKey: ["exam-files", examId],
    queryFn: () => ExamsService.readExamFiles({ examId }),
  })
  const exam = useQuery({
    queryKey: ["exam", examId],
    queryFn: () => ExamsService.readExam({ examId }),
  })
  const runs = useQuery({
    queryKey: ["question-recognition-runs", examId],
    queryFn: () =>
      workflowApi<{ data: RecognitionRun[] }>(
        `/exams/${examId}/question-recognition-runs`,
      ),
    refetchInterval: 2500,
  })
  const activeRun = useQuery({
    queryKey: ["question-recognition-run", activeRunId],
    queryFn: () =>
      workflowApi<RecognitionRun>(
        `/exams/${examId}/question-recognition-runs/${activeRunId}`,
      ),
    enabled: Boolean(activeRunId),
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.status ?? "")
        ? 2000
        : false,
  })
  const items = useQuery({
    queryKey: ["question-recognition-items", activeRunId],
    queryFn: () =>
      workflowApi<RecognitionItem[]>(
        `/exams/${examId}/question-recognition-runs/${activeRunId}/items`,
      ),
    enabled: Boolean(activeRunId),
    refetchInterval: activeRun.data?.status === "running" ? 2500 : false,
  })

  const blankDocuments = (files.data?.data ?? []).filter(
    (document) => document.document_type === "blank_exam",
  )
  useEffect(() => {
    if (!selectedDocuments.length && blankDocuments.length)
      setSelectedDocuments(blankDocuments.map((document) => document.id))
  }, [blankDocuments, selectedDocuments.length])
  useEffect(() => {
    if (activeRunId) return
    const requestedRun = runs.data?.data?.find(
      (run) => run.id === requestedRunId,
    )
    if (requestedRun) setActiveRunId(requestedRun.id)
    else if (runs.data?.data?.[0]) setActiveRunId(runs.data.data[0].id)
  }, [activeRunId, requestedRunId, runs.data?.data])
  useEffect(() => {
    if (!items.data) return
    setDrafts(Object.fromEntries(items.data.map((item) => [item.id, item])))
    setDirtyIds(new Set())
    setSaveErrors({})
  }, [items.data])

  const updateDraft = (id: string, next: RecognitionItem) => {
    setDrafts((current) => ({ ...current, [id]: next }))
    setDirtyIds((current) => new Set(current).add(id))
  }

  const missingQuestions = useMemo(
    () =>
      findMissingQuestions(
        (items.data ?? []).map((item) => drafts[item.id] ?? item),
      ),
    [items.data, drafts],
  )

  const createRun = useMutation({
    mutationFn: () =>
      workflowApi<RecognitionRun>(
        `/exams/${examId}/question-recognition-runs`,
        {
          method: "POST",
          body: JSON.stringify({ document_ids: selectedDocuments }),
        },
      ),
    onSuccess: (run) => {
      setActiveRunId(run.id)
      showSuccessToast("题目识别任务已启动")
      queryClient.invalidateQueries({
        queryKey: ["question-recognition-runs", examId],
      })
    },
    onError: (error) =>
      showErrorToast(error instanceof Error ? error.message : "启动失败"),
  })
  const confirmRun = useMutation({
    mutationFn: () =>
      workflowApi<RecognitionRun>(
        `/exams/${examId}/question-recognition-runs/${activeRunId}/confirm`,
        { method: "POST" },
      ),
    onSuccess: async () => {
      showSuccessToast("题目已确认，正在进入标准答案")
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["question-recognition-run", activeRunId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["question-recognition-items", activeRunId],
        }),
        queryClient.invalidateQueries({
          queryKey: ["confirmed-questions", examId],
        }),
      ])
      navigate({ to: "/exams/$examId/answers", params: { examId } })
    },
    onError: (error) =>
      showErrorToast(error instanceof Error ? error.message : "确认失败"),
  })
  const saveAll = useMutation({
    mutationFn: () =>
      Promise.all(
        [...dirtyIds].map(async (id) => {
          const draft = drafts[id]
          try {
            await workflowApi<RecognitionItem>(
              `/exams/${examId}/question-recognition-items/${id}`,
              {
                method: "PATCH",
                body: JSON.stringify({
                  question_key: draft.question_key,
                  label: draft.label,
                  question_text: draft.question_text,
                  student_answer_text: draft.student_answer_text,
                  question_type: draft.question_type,
                  knowledge_point: draft.knowledge_point,
                  difficulty: draft.difficulty,
                  confidence: draft.confidence,
                  status: draft.status,
                }),
              },
            )
            return { id, error: null as string | null }
          } catch (error) {
            return {
              id,
              error: error instanceof Error ? error.message : "保存失败",
            }
          }
        }),
      ),
    onSuccess: (results) => {
      const failed = results.filter((result) => result.error)
      setDirtyIds(new Set(failed.map((result) => result.id)))
      setSaveErrors(
        Object.fromEntries(
          failed.map((result) => [result.id, result.error as string]),
        ),
      )
      if (failed.length) {
        showErrorToast(`${failed.length} 道题目保存失败，请修正后重试`)
      } else {
        showSuccessToast("全部修改已保存")
      }
    },
  })
  const current = activeRun.data
  const completed =
    current && ["completed", "completed_with_errors"].includes(current.status)
  const reviewItemCount = (items.data ?? []).filter(
    (item) => item.confidence !== null && item.confidence < 0.8,
  ).length
  const timing = current?.timing ?? {}

  return (
    <div className="grid gap-6">
      <p className="max-w-3xl text-sm text-muted-foreground">
        新卷子只需要做一次：系统自动从上传的卷子图片/PDF
        中提取印刷题目和题块；如果源图是学生卷，卷面作答只作为旁证展示，不会写入正式题干。确认识别结果后再进入标准答案页面生成或导入答案。
      </p>

      <section className="grid gap-4 rounded-2xl border bg-card p-5 shadow-card">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="font-semibold text-sm">已导入的卷子</h2>
            <div className="text-muted-foreground text-sm">
              已选 {selectedDocuments.length} / {blankDocuments.length}{" "}
              个文件。优先选择空白卷；没有空白卷时，可选择一份代表学生卷识别题目内容。
            </div>
          </div>
          <Button
            disabled={!selectedDocuments.length || createRun.isPending}
            onClick={() => createRun.mutate()}
            className="bg-gradient-primary text-white hover:opacity-90"
          >
            {createRun.isPending ? (
              <Loader2 className="animate-spin" />
            ) : (
              <ScanSearch />
            )}
            开始识别
          </Button>
        </div>
        {blankDocuments.length === 0 ? (
          <div className="rounded-xl border border-dashed px-4 py-6">
            <div className="text-muted-foreground text-sm">
              还没有可识别的卷子。请先导入空白卷或一份代表学生卷。
            </div>
            {exam.data && (
              <ImportCenterDialog
                exam={exam.data}
                initialTab="blank"
                trigger={
                  <Button className="mt-3" size="sm">
                    <Upload />
                    导入模板卷
                  </Button>
                }
              />
            )}
          </div>
        ) : null}
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {blankDocuments.map((document) => (
            <div
              key={document.id}
              className="flex min-w-0 items-center gap-3 rounded-xl border px-3 py-3 text-sm transition-colors hover:bg-secondary/50"
            >
              <Checkbox
                checked={selectedDocuments.includes(document.id)}
                onCheckedChange={(checked) =>
                  setSelectedDocuments((currentIds) =>
                    checked
                      ? [...currentIds, document.id]
                      : currentIds.filter((id) => id !== document.id),
                  )
                }
              />
              <FileSearch className="size-4 shrink-0 text-muted-foreground" />
              <span className="truncate">
                {document.stored_file.original_filename}
              </span>
              <Tag variant="indigo" className="ml-auto shrink-0">
                {document.page_count} 页
              </Tag>
            </div>
          ))}
        </div>
      </section>

      {current && (
        <section className="grid gap-4 rounded-2xl border bg-card p-5 shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <h2 className="font-semibold text-sm">识别批次</h2>
              {statusBadge(current.status, Boolean(current.confirmed_at))}
            </div>
            <select
              className="h-9 max-w-72 rounded-md border bg-background px-3 text-sm"
              value={activeRunId ?? ""}
              onChange={(event) => setActiveRunId(event.target.value)}
            >
              {(runs.data?.data ?? []).map((run, index) => (
                <option key={run.id} value={run.id}>
                  批次 {runs.data!.data.length - index} · {run.status}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border bg-border md:max-w-md">
            <div className="bg-background px-4 py-3">
              <div className="text-muted-foreground text-xs">题目数</div>
              <div className="mt-1 font-medium text-sm">
                {items.data?.length ?? current.item_count}
              </div>
            </div>
            <div className="bg-background px-4 py-3">
              <div className="text-muted-foreground text-xs">需要复核</div>
              <div className="mt-1" data-testid="review-item-count">
                <span className="font-medium text-sm">
                  {reviewItemCount} 道
                </span>
              </div>
            </div>
          </div>
          <details className="rounded-xl border px-4 py-3">
            <summary className="cursor-pointer text-muted-foreground text-sm">
              批次详情（调试）
            </summary>
            <div className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-xl border bg-border md:grid-cols-5">
              {[
                ["方向检测", timing.orientationMs],
                ["版面分割", timing.layoutMs],
                ["裁切", timing.cropMs],
                ["文字识别", timing.ocrMs],
                ["总耗时", timing.totalElapsedMs],
              ].map(([label, value]) => (
                <div key={String(label)} className="bg-background px-4 py-3">
                  <div className="text-muted-foreground text-xs">{label}</div>
                  <div className="mt-1 font-medium text-sm tabular-nums">
                    {formatMs(value as number | undefined)}
                  </div>
                </div>
              ))}
            </div>
          </details>
          {current.error_message && (
            <div className="rounded-xl border border-destructive px-4 py-3 text-destructive text-sm">
              {current.error_message}
            </div>
          )}
        </section>
      )}

      {current && ["queued", "running"].includes(current.status) ? (
        <div className="flex min-h-48 items-center justify-center gap-2 rounded-2xl border bg-card text-muted-foreground text-sm shadow-card">
          <Loader2 className="animate-spin" />
          系统正在校正页面、识别题目并整理内容
        </div>
      ) : items.data?.length ? (
        <>
          {missingQuestions.length > 0 && (
            <div
              className="rounded-xl border border-amber-500/40 bg-amber-500/5 px-4 py-3 text-sm"
              data-testid="missing-questions-warning"
            >
              <span className="font-medium text-amber-700 dark:text-amber-400">
                题号不连续，可能漏识别了 {missingQuestions.length} 道题：
              </span>
              <span className="text-muted-foreground">
                {missingQuestions.join("、")}
                。请对照原卷检查——漏掉的题可以重新识别或联系管理员补录。
              </span>
            </div>
          )}
          <section className="overflow-hidden rounded-2xl border bg-card shadow-card">
            <div className="border-b px-5 py-4">
              <h2 className="font-semibold text-sm">题目与卷面作答</h2>
              <div className="text-muted-foreground text-xs">
                保留项将在确认后写入正式题库；卷面作答只用于人工核对，不会进入标准题干。点击题目行展开编辑
              </div>
            </div>
            <div className="divide-y">
              {(items.data ?? []).map((item) => (
                <QuestionItemRow
                  key={item.id}
                  item={drafts[item.id] ?? item}
                  locked={Boolean(current?.confirmed_at)}
                  error={saveErrors[item.id]}
                  onChange={(next) => updateDraft(item.id, next)}
                />
              ))}
            </div>
          </section>
          <div className="sticky bottom-4 z-10 flex flex-wrap items-center justify-between gap-3 rounded-2xl border bg-card px-4 py-3 shadow-card-lg">
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                disabled={
                  Boolean(current?.confirmed_at) ||
                  !dirtyIds.size ||
                  saveAll.isPending
                }
                onClick={() => saveAll.mutate()}
              >
                {saveAll.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <Save />
                )}
                保存全部修改
              </Button>
              {dirtyIds.size > 0 && (
                <Tag variant="amber">{dirtyIds.size} 条未保存</Tag>
              )}
              {Object.keys(saveErrors).length > 0 && (
                <Tag variant="red">
                  {Object.keys(saveErrors).length} 条保存失败
                </Tag>
              )}
            </div>
            <Button
              disabled={
                !completed ||
                Boolean(current?.confirmed_at) ||
                confirmRun.isPending ||
                dirtyIds.size > 0
              }
              onClick={() => confirmRun.mutate()}
              className="bg-gradient-primary text-white hover:opacity-90"
            >
              {confirmRun.isPending ? (
                <Loader2 className="animate-spin" />
              ) : current?.confirmed_at ? (
                <CheckCircle2 />
              ) : (
                <Check />
              )}
              {current?.confirmed_at ? "已确认" : "确认题目并进入标准答案"}
            </Button>
          </div>
        </>
      ) : (
        <EmptyState
          icon={Clock3}
          title="尚无题目识别结果"
          description="选择上方已导入的卷子并启动识别后，题目会显示在这里"
          className="bg-card shadow-card"
        />
      )}
    </div>
  )
}
