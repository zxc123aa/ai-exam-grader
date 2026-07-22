import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import {
  Check,
  CheckCircle2,
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
import { ImportCenterDialog } from "@/components/Exams/ImportCenterDialog"
import { Badge } from "@/components/ui/badge"
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
import { workflowApi } from "@/lib/workflow-api"

export const Route = createFileRoute("/_layout/exams_/$examId/questions")({
  component: QuestionWorkspace,
  validateSearch: z.object({ runId: z.string().optional() }),
  head: () => ({ meta: [{ title: "识别内容 - 智阅卷" }] }),
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
  if (confirmed) return <Badge className="bg-emerald-600">已确认</Badge>
  if (status === "running" || status === "queued")
    return <Badge variant="secondary">识别中</Badge>
  if (status === "failed") return <Badge variant="destructive">失败</Badge>
  if (status === "completed_with_errors")
    return <Badge variant="outline">待处理异常</Badge>
  return <Badge variant="secondary">待确认</Badge>
}

function formatMs(value?: number) {
  if (value === undefined || value === null) return "—"
  return value >= 1000 ? `${(value / 1000).toFixed(2)} 秒` : `${value} 毫秒`
}

function QuestionItemEditor({
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
  const regionCount = item.region_ids.length || item.region_snapshots.length

  return (
    <article
      className={`grid gap-4 border-b px-4 py-5 last:border-b-0${
        error ? " border-l-2 border-l-destructive" : ""
      }`}
      data-testid={`recognition-item-${item.id}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Checkbox
            checked={item.status !== "excluded"}
            disabled={locked}
            aria-label={`保留${item.label}`}
            onCheckedChange={(checked) =>
              onChange({
                ...item,
                status: checked ? "draft" : "excluded",
              })
            }
          />
          <span className="font-medium">{item.label}</span>
          <Badge variant="outline">{regionCount} 个区域</Badge>
          <Badge
            variant={
              item.confidence !== null && item.confidence < 0.7
                ? "destructive"
                : "secondary"
            }
          >
            {item.confidence === null
              ? "无置信度"
              : `${Math.round(item.confidence * 100)}%`}
          </Badge>
        </div>
        {error && <span className="text-xs text-destructive">{error}</span>}
      </div>

      <div className="grid gap-3 md:grid-cols-[140px_180px_minmax(0,1fr)]">
        <div className="grid gap-2">
          <Label>题目标识</Label>
          <Input
            value={item.question_key}
            disabled={locked || item.status === "excluded"}
            onChange={(event) =>
              onChange({ ...item, question_key: event.target.value })
            }
          />
        </div>
        <div className="grid gap-2">
          <Label>题型</Label>
          <Select
            value={item.question_type ?? "未知"}
            disabled={locked || item.status === "excluded"}
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
            disabled={locked || item.status === "excluded"}
            onChange={(event) =>
              onChange({ ...item, label: event.target.value })
            }
          />
        </div>
      </div>

      <div className="grid gap-2">
        <Label>印刷题目与选项</Label>
        <textarea
          className="border-input min-h-36 w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          value={item.question_text}
          disabled={locked || item.status === "excluded"}
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
          <div className="whitespace-pre-wrap text-sm">
            {item.student_answer_text}
          </div>
        </div>
      )}
      {item.notes && (
        <div className="text-xs text-muted-foreground">{item.notes}</div>
      )}
    </article>
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
  const averageConfidence = useMemo(() => {
    const values = (items.data ?? [])
      .map((item) => item.confidence)
      .filter((value): value is number => value !== null)
    return values.length
      ? values.reduce((sum, value) => sum + value, 0) / values.length
      : null
  }, [items.data])
  const timing = current?.timing ?? {}

  return (
    <div className="grid gap-6">
      <p className="max-w-3xl text-sm text-muted-foreground">
        新卷子只需要做一次：先用 Gemini
        从上传的卷子图片/PDF中提取印刷题目和题块；如果源图是学生卷，卷面作答只作为旁证展示，不会写入正式题干。确认识别结果后再进入标准答案页面生成或导入答案。
      </p>

      <section className="grid gap-4 border-y py-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="font-semibold">已导入的卷子</h2>
            <div className="text-sm text-muted-foreground">
              已选 {selectedDocuments.length} / {blankDocuments.length}{" "}
              个文件。优先选择空白卷；没有空白卷时，可选择一份代表学生卷识别题目内容。
            </div>
          </div>
          <Button
            disabled={!selectedDocuments.length || createRun.isPending}
            onClick={() => createRun.mutate()}
          >
            {createRun.isPending ? (
              <Loader2 className="animate-spin" />
            ) : (
              <ScanSearch />
            )}
            识别内容
          </Button>
        </div>
        {blankDocuments.length === 0 ? (
          <div className="rounded-md border border-dashed px-4 py-6">
            <div className="text-sm text-muted-foreground">
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
              className="flex min-w-0 items-center gap-3 rounded-md border px-3 py-3 text-sm"
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
              <Badge variant="outline" className="ml-auto shrink-0">
                {document.page_count} 页
              </Badge>
            </div>
          ))}
        </div>
      </section>

      {current && (
        <section className="grid gap-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <h2 className="font-semibold">识别批次</h2>
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
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border bg-border md:max-w-md">
            <div className="bg-background px-4 py-3">
              <div className="text-xs text-muted-foreground">题目数</div>
              <div className="mt-1 text-sm font-medium">
                {items.data?.length ?? current.item_count}
              </div>
            </div>
            <div className="bg-background px-4 py-3">
              <div className="text-xs text-muted-foreground">平均置信度</div>
              <div
                className="mt-1 text-sm font-medium"
                data-testid="average-confidence"
              >
                {averageConfidence === null
                  ? "—"
                  : `${Math.round(averageConfidence * 100)}%`}
              </div>
            </div>
          </div>
          <details className="rounded-md border px-4 py-3">
            <summary className="cursor-pointer text-sm text-muted-foreground">
              批次详情（调试）
            </summary>
            <div className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-md border bg-border md:grid-cols-5">
              {[
                ["方向检测", timing.orientationMs],
                ["版面分割", timing.layoutMs],
                ["裁切", timing.cropMs],
                ["OCR", timing.ocrMs],
                ["总耗时", timing.totalElapsedMs],
              ].map(([label, value]) => (
                <div key={String(label)} className="bg-background px-4 py-3">
                  <div className="text-xs text-muted-foreground">{label}</div>
                  <div className="mt-1 text-sm font-medium tabular-nums">
                    {formatMs(value as number | undefined)}
                  </div>
                </div>
              ))}
            </div>
          </details>
          {current.error_message && (
            <div className="rounded-md border border-destructive px-4 py-3 text-sm text-destructive">
              {current.error_message}
            </div>
          )}
        </section>
      )}

      {current && ["queued", "running"].includes(current.status) ? (
        <div className="flex min-h-48 items-center justify-center gap-2 border-y text-sm text-muted-foreground">
          <Loader2 className="animate-spin" />
          参考算法正在执行旋转、分割、裁切和并发 OCR
        </div>
      ) : items.data?.length ? (
        <>
          <section className="overflow-hidden rounded-md border">
            <div className="border-b px-4 py-3">
              <h2 className="font-semibold">题目与卷面作答</h2>
              <div className="text-xs text-muted-foreground">
                保留项将在确认后写入正式题库；卷面作答只用于人工核对，不会进入标准题干
              </div>
            </div>
            {(items.data ?? []).map((item) => (
              <QuestionItemEditor
                key={item.id}
                item={drafts[item.id] ?? item}
                locked={Boolean(current?.confirmed_at)}
                error={saveErrors[item.id]}
                onChange={(next) => updateDraft(item.id, next)}
              />
            ))}
          </section>
          <div className="sticky bottom-4 z-10 flex flex-wrap items-center justify-between gap-3 rounded-md border bg-background px-4 py-3 shadow-md">
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
                <Badge variant="secondary">{dirtyIds.size} 条未保存</Badge>
              )}
              {Object.keys(saveErrors).length > 0 && (
                <Badge variant="destructive">
                  {Object.keys(saveErrors).length} 条保存失败
                </Badge>
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
        <div className="flex min-h-48 flex-col items-center justify-center gap-2 border-y text-sm text-muted-foreground">
          <Clock3 className="size-5" />
          尚无题目识别结果
        </div>
      )}
    </div>
  )
}
