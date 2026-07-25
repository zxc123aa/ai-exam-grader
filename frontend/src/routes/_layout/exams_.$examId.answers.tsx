import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  BookCheck,
  Check,
  ChevronDown,
  FileKey2,
  History,
  Loader2,
  Save,
  Sparkles,
  Upload,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { ExamsService } from "@/client"
import { ConfBadge } from "@/components/Common/ConfBadge"
import { EmptyState } from "@/components/Common/EmptyState"
import { Tag, type TagVariant } from "@/components/Common/Tag"
import { ImportCenterDialog } from "@/components/Exams/ImportCenterDialog"
import { ScoringPointsEditor } from "@/components/Exams/ScoringPointsEditor"
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useCustomToast from "@/hooks/useCustomToast"
import { cn } from "@/lib/utils"
import { workflowApi } from "@/lib/workflow-api"

export const Route = createFileRoute("/_layout/exams_/$examId/answers")({
  component: AnswerWorkspace,
  head: () => ({ meta: [{ title: "标准答案 - 点凡阅卷" }] }),
})

type Question = {
  id: string
  question_key: string
  label: string
  question_text: string
  question_type: string | null
  status: "draft" | "confirmed"
}

type AnswerRun = {
  id: string
  source_type: "model" | "document"
  provider: string
  model: string
  document_ids: string[]
  status:
    | "queued"
    | "running"
    | "completed"
    | "completed_with_errors"
    | "failed"
  timing: {
    modelMs?: number
    totalElapsedMs?: number
    usedModels?: string[]
    usedProviders?: string[]
    fallbackUsed?: boolean
  }
  item_count: number
  error_message: string | null
  confirmed_at: string | null
}

type AnswerItem = {
  id: string
  question_id: string | null
  source_question_key: string | null
  answer_text: string
  max_score: number
  rubric_text: string | null
  scoring_points: Record<string, unknown>[]
  confidence: number | null
  match_reason: string | null
  status:
    | "queued"
    | "running"
    | "matched"
    | "conflict"
    | "unmatched"
    | "failed"
    | "confirmed"
  revision_id: string | null
  error_message: string | null
}

type Revision = {
  id: string
  standard_answer_id: string
  question_id: string
  revision_number: number
  question_key: string
  question_text: string
  answer_text: string
  max_score: number
  rubric_text: string | null
  scoring_points: Record<string, unknown>[]
  source_provider: string | null
  source_model: string | null
  generation_confidence: number | null
  content_hash: string
  status: "draft" | "published"
  created_at: string
  published_at: string | null
}

const providerModels: Record<string, string[]> = {
  pomoai: [
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-opus-4-6",
    "gemini-3.5-flash",
    "grok-4.5",
  ],
  fluxnode_gemini: ["gemini-3.5-flash"],
  fluxnode_grok: ["grok-4.5"],
  kimi: [
    "kimi-k2.7-code",
    "kimi-k2.7-code-highspeed",
    "kimi-k2.6",
    "kimi-k2.5",
  ],
}

const providerLabels: Record<string, string> = {
  pomoai: "聚合平台",
  fluxnode_gemini: "智能识别",
  fluxnode_grok: "Grok",
  kimi: "Kimi",
}

function formatMs(value?: number) {
  if (value === undefined) return "—"
  return value >= 1000 ? `${(value / 1000).toFixed(2)} 秒` : `${value} 毫秒`
}

const RUN_STATUS_LABELS: Record<AnswerRun["status"], string> = {
  queued: "排队中",
  running: "生成中",
  completed: "已完成",
  completed_with_errors: "部分失败",
  failed: "失败",
}

function itemStatus(status: AnswerItem["status"]) {
  const map: Record<AnswerItem["status"], [string, TagVariant]> = {
    queued: ["排队中", "indigo"],
    running: ["生成中", "sky"],
    matched: ["已匹配", "violet"],
    conflict: ["匹配冲突", "amber"],
    unmatched: ["未匹配", "amber"],
    failed: ["生成失败", "red"],
    confirmed: ["已确认", "mint"],
  }
  return map[status]
}

type AnswerDraft = {
  questionId: string
  answerText: string
  maxScore: string
  rubricText: string
  scoringPoints: Record<string, unknown>[]
}

function AnswerItemRow({
  item,
  draft,
  questions,
  locked,
  error,
  onChange,
}: {
  item: AnswerItem
  draft: AnswerDraft
  questions: Question[]
  locked: boolean
  error?: string
  onChange: (patch: Partial<AnswerDraft>) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [statusLabel, statusVariant] = itemStatus(item.status)
  const question = questions.find(
    (candidate) => candidate.id === draft.questionId,
  )

  return (
    <div
      className={error ? "border-l-2 border-l-destructive" : ""}
      data-testid={`answer-item-${item.id}`}
    >
      <button
        type="button"
        aria-expanded={expanded}
        className="flex w-full cursor-pointer items-center gap-3 px-4 py-3 text-left text-sm hover:bg-muted/50"
        onClick={() => setExpanded((current) => !current)}
      >
        <span className="max-w-56 shrink-0 truncate whitespace-nowrap font-medium">
          {question?.label ?? item.source_question_key ?? "未匹配条目"}
        </span>
        <span className="min-w-0 flex-1">
          <span
            className="block truncate text-muted-foreground"
            title={draft.answerText}
          >
            {draft.answerText || "—"}
          </span>
          {(item.match_reason || item.error_message) && (
            <span className="block truncate text-muted-foreground text-xs">
              {item.error_message || item.match_reason}
            </span>
          )}
        </span>
        <Tag variant="indigo" className="shrink-0">
          满分 {draft.maxScore || "—"}
        </Tag>
        <Tag variant={statusVariant} className="shrink-0">
          {statusLabel}
        </Tag>
        {item.confidence !== null && item.confidence < 0.8 && (
          <ConfBadge value={item.confidence * 100} className="shrink-0" />
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

      {expanded && (
        <div className="grid gap-4 border-t bg-muted/20 px-4 py-5">
          <div className="grid gap-3 md:grid-cols-[minmax(220px,1fr)_140px]">
            <div className="grid gap-2">
              <Label>匹配题目</Label>
              <Select
                value={draft.questionId}
                disabled={locked}
                onValueChange={(value) => onChange({ questionId: value })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="unassigned">不匹配，保留待处理</SelectItem>
                  {questions.map((candidate) => (
                    <SelectItem key={candidate.id} value={candidate.id}>
                      {candidate.question_key} · {candidate.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label>满分</Label>
              <Input
                inputMode="decimal"
                value={draft.maxScore}
                disabled={locked}
                onChange={(event) => onChange({ maxScore: event.target.value })}
              />
            </div>
          </div>
          {question && (
            <div className="whitespace-pre-wrap border-l-2 pl-3 text-muted-foreground text-sm">
              {question.question_text}
            </div>
          )}
          <div className="grid gap-2">
            <Label>标准答案</Label>
            <textarea
              className="border-input min-h-32 w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={draft.answerText}
              disabled={locked}
              onChange={(event) => onChange({ answerText: event.target.value })}
            />
          </div>
          <div className="grid gap-2">
            <Label>总体评分规则</Label>
            <textarea
              className="border-input min-h-24 w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={draft.rubricText}
              disabled={locked}
              onChange={(event) => onChange({ rubricText: event.target.value })}
            />
          </div>
          <div className="grid gap-2">
            <Label>评分点</Label>
            <ScoringPointsEditor
              points={draft.scoringPoints}
              disabled={locked}
              onChange={(points) => onChange({ scoringPoints: points })}
            />
          </div>
          {item.confidence !== null && (
            <div className="flex items-center gap-1 text-muted-foreground text-xs">
              置信度
              <ConfBadge value={item.confidence * 100} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function AnswerWorkspace() {
  const { examId } = Route.useParams()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [mode, setMode] = useState<"model" | "document">("model")
  const [provider, setProvider] = useState("pomoai")
  const [model, setModel] = useState("gpt-5.6-sol")
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([])
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<Record<string, AnswerDraft>>({})
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
  const questions = useQuery({
    queryKey: ["confirmed-questions", examId],
    queryFn: () =>
      workflowApi<{ data: Question[]; count: number }>(
        `/exams/${examId}/questions`,
      ),
  })
  const runs = useQuery({
    queryKey: ["answer-preparation-runs", examId],
    queryFn: () =>
      workflowApi<{ data: AnswerRun[] }>(
        `/exams/${examId}/answer-preparation-runs`,
      ),
    refetchInterval: 2500,
  })
  const run = useQuery({
    queryKey: ["answer-preparation-run", activeRunId],
    queryFn: () =>
      workflowApi<AnswerRun>(
        `/exams/${examId}/answer-preparation-runs/${activeRunId}`,
      ),
    enabled: Boolean(activeRunId),
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.status ?? "")
        ? 2000
        : false,
  })
  const items = useQuery({
    queryKey: ["answer-preparation-items", activeRunId],
    queryFn: () =>
      workflowApi<AnswerItem[]>(
        `/exams/${examId}/answer-preparation-runs/${activeRunId}/items`,
      ),
    enabled: Boolean(activeRunId),
    refetchInterval: run.data?.status === "running" ? 2500 : false,
  })
  const revisions = useQuery({
    queryKey: ["answer-revisions", examId],
    queryFn: () =>
      workflowApi<{ data: Revision[]; count: number }>(
        `/exams/${examId}/standard-answers/revisions`,
      ),
  })
  useEffect(() => {
    if (!activeRunId && runs.data?.data?.[0])
      setActiveRunId(runs.data.data[0].id)
  }, [activeRunId, runs.data?.data])
  useEffect(() => {
    if (!items.data) return
    setDrafts(
      Object.fromEntries(
        items.data.map((item) => [
          item.id,
          {
            questionId: item.question_id ?? "unassigned",
            answerText: item.answer_text,
            maxScore: String(item.max_score),
            rubricText: item.rubric_text ?? "",
            scoringPoints: item.scoring_points,
          },
        ]),
      ),
    )
    setDirtyIds(new Set())
    setSaveErrors({})
  }, [items.data])

  const updateDraft = (id: string, patch: Partial<AnswerDraft>) => {
    setDrafts((current) => ({
      ...current,
      [id]: { ...current[id], ...patch },
    }))
    setDirtyIds((current) => new Set(current).add(id))
  }

  const patchItem = (id: string, draft: AnswerDraft) => {
    const score = Number(draft.maxScore)
    if (!Number.isFinite(score) || score <= 0) throw new Error("满分必须大于 0")
    const points = draft.scoringPoints
      .map((point, index) => ({
        ...point,
        id: String(point.id ?? `p${index + 1}`),
        description: String(point.description ?? "").trim(),
        points: Number(point.points ?? 0),
        required: point.required ?? true,
      }))
      .filter((point) => point.description)
    for (const point of points) {
      if (
        !Number.isFinite(point.points as number) ||
        (point.points as number) < 0
      )
        throw new Error("评分点分值无效")
    }
    return workflowApi<AnswerItem>(
      `/exams/${examId}/answer-preparation-items/${id}`,
      {
        method: "PATCH",
        body: JSON.stringify({
          question_id:
            draft.questionId === "unassigned" ? null : draft.questionId,
          answer_text: draft.answerText,
          max_score: score,
          rubric_text: draft.rubricText,
          scoring_points: points,
          status: draft.questionId === "unassigned" ? "unmatched" : "matched",
        }),
      },
    )
  }

  const answerDocuments = (files.data?.data ?? []).filter(
    (document) => document.document_type === "answer_key",
  )
  const confirmedQuestions = (questions.data?.data ?? []).filter(
    (question) => question.status === "confirmed",
  )
  const averageConfidence = useMemo(() => {
    const values = (items.data ?? [])
      .map((item) => item.confidence)
      .filter((value): value is number => value !== null)
    return values.length
      ? values.reduce((sum, value) => sum + value, 0) / values.length
      : null
  }, [items.data])
  const draftTotalScore = useMemo(
    () =>
      (items.data ?? []).reduce(
        (total, item) => total + Number(item.max_score || 0),
        0,
      ),
    [items.data],
  )
  const draftRevisions = (revisions.data?.data ?? []).filter(
    (revision) => revision.status === "draft",
  )
  const publishedQuestions = new Set(
    (revisions.data?.data ?? [])
      .filter((revision) => revision.status === "published")
      .map((revision) => revision.question_id),
  ).size

  const create = useMutation({
    mutationFn: () =>
      workflowApi<AnswerRun>(`/exams/${examId}/answer-preparation-runs`, {
        method: "POST",
        body: JSON.stringify({
          source_type: mode,
          provider,
          model,
          document_ids: mode === "document" ? selectedDocuments : [],
        }),
      }),
    onSuccess: (created) => {
      setActiveRunId(created.id)
      showSuccessToast(
        mode === "model" ? "模型解题任务已启动" : "答案文档整理任务已启动",
      )
      queryClient.invalidateQueries({
        queryKey: ["answer-preparation-runs", examId],
      })
    },
    onError: (error) =>
      showErrorToast(error instanceof Error ? error.message : "启动失败"),
  })
  const confirm = useMutation({
    mutationFn: () =>
      workflowApi<AnswerRun>(
        `/exams/${examId}/answer-preparation-runs/${activeRunId}/confirm`,
        { method: "POST" },
      ),
    onSuccess: () => {
      showSuccessToast("答案与评分准则已确认，已生成待发布修订")
      queryClient.invalidateQueries({
        queryKey: ["answer-preparation-run", activeRunId],
      })
      queryClient.invalidateQueries({
        queryKey: ["answer-preparation-items", activeRunId],
      })
      queryClient.invalidateQueries({ queryKey: ["answer-revisions", examId] })
    },
    onError: (error) =>
      showErrorToast(error instanceof Error ? error.message : "确认失败"),
  })
  const publish = useMutation({
    mutationFn: () =>
      workflowApi<{ data: Revision[] }>(
        `/exams/${examId}/standard-answers/publish`,
        { method: "POST", body: JSON.stringify({ revision_ids: [] }) },
      ),
    onSuccess: () => {
      showSuccessToast("标准答案版本已发布并锁定")
      queryClient.invalidateQueries({ queryKey: ["answer-revisions", examId] })
    },
    onError: (error) =>
      showErrorToast(error instanceof Error ? error.message : "发布失败"),
  })
  const saveAll = useMutation({
    mutationFn: () =>
      Promise.all(
        [...dirtyIds].map(async (id) => {
          try {
            await patchItem(id, drafts[id])
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
        showErrorToast(`${failed.length} 条答案保存失败，请修正后重试`)
      } else {
        showSuccessToast("全部修改已保存")
      }
    },
  })
  const current = run.data
  const completed =
    current && ["completed", "completed_with_errors"].includes(current.status)

  return (
    <div className="grid gap-6">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <p className="max-w-3xl text-muted-foreground text-sm">
          标准答案只在新卷子首次建库时准备一次。默认用 GPT-5.6 SOL
          根据已确认题目解题，也可以上传答案文档整理；所有答案和评分准则必须人工确认，发布后形成不可变版本，后续批改复用该版本。
        </p>
        <div className="flex flex-wrap gap-2">
          <Tag variant="mint">{confirmedQuestions.length} 道已确认题目</Tag>
          <Tag variant="neutral">{publishedQuestions} 道已发布</Tag>
        </div>
      </header>

      {confirmedQuestions.length === 0 ? (
        <div className="grid gap-4">
          <EmptyState
            icon={BookCheck}
            title="尚无已确认题目"
            description="先在“确认题目”页确认题目，再回来准备标准答案"
            className="bg-card shadow-card"
          />
          <div className="flex justify-center">
            <Button asChild>
              <Link to="/exams/$examId/questions" params={{ examId }}>
                前往确认题目
              </Link>
            </Button>
          </div>
        </div>
      ) : (
        <>
          <section className="grid gap-5 rounded-2xl border bg-card p-5 shadow-card">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
              <div className="grid gap-3">
                <Tabs
                  value={mode}
                  onValueChange={(value) =>
                    setMode(value as "model" | "document")
                  }
                >
                  <TabsList>
                    <TabsTrigger value="model">
                      <Sparkles />
                      模型独立解题
                    </TabsTrigger>
                    <TabsTrigger value="document">
                      <Upload />
                      导入答案文档
                    </TabsTrigger>
                  </TabsList>
                </Tabs>
                <div className="flex flex-wrap gap-3">
                  <div className="grid min-w-44 gap-1">
                    <Label>提供者</Label>
                    <Select
                      value={provider}
                      onValueChange={(value) => {
                        setProvider(value)
                        setModel(providerModels[value][0])
                      }}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {Object.keys(providerModels).map((value) => (
                          <SelectItem key={value} value={value}>
                            {providerLabels[value] ?? value}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="grid min-w-60 gap-1">
                    <Label>模型</Label>
                    <Select value={model} onValueChange={setModel}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {providerModels[provider].map((value) => (
                          <SelectItem key={value} value={value}>
                            {value}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="max-w-3xl text-xs text-muted-foreground">
                  模型独立解题会读取已确认题干和题目裁图生成标准答案、满分和评分点；答案文档模式只整理文档中已有答案，未匹配或冲突项需要人工处理。
                </div>
              </div>
              <Button
                disabled={
                  create.isPending ||
                  (mode === "document" && !selectedDocuments.length)
                }
                onClick={() => create.mutate()}
                className="bg-gradient-primary text-white hover:opacity-90"
              >
                {create.isPending ? (
                  <Loader2 className="animate-spin" />
                ) : mode === "model" ? (
                  <Sparkles />
                ) : (
                  <FileKey2 />
                )}
                {mode === "model" ? "生成参考答案" : "整理答案文档"}
              </Button>
            </div>

            {mode === "document" && (
              <div className="grid gap-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="text-xs text-muted-foreground">
                    勾选要整理的答案文档；还没有文档时先去导入中心上传。
                  </div>
                  {exam.data && (
                    <ImportCenterDialog
                      exam={exam.data}
                      initialTab="answer"
                      trigger={
                        <Button variant="outline" size="sm">
                          <Upload />
                          去导入
                        </Button>
                      }
                    />
                  )}
                </div>
                <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                  {answerDocuments.map((document) => (
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
                      <FileKey2 className="size-4 shrink-0 text-muted-foreground" />
                      <span className="truncate">
                        {document.stored_file.original_filename}
                      </span>
                      <Tag variant="indigo" className="ml-auto">
                        {document.page_count} 页
                      </Tag>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>

          {current && (
            <section className="grid gap-4 rounded-2xl border bg-card p-5 shadow-card">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <h2 className="font-semibold text-sm">答案准备批次</h2>
                  <Tag
                    variant={
                      current.confirmed_at
                        ? "mint"
                        : current.status === "failed"
                          ? "red"
                          : current.status === "completed_with_errors"
                            ? "amber"
                            : "sky"
                    }
                  >
                    {current.confirmed_at
                      ? "已确认"
                      : (RUN_STATUS_LABELS[current.status] ?? current.status)}
                  </Tag>
                </div>
                <select
                  className="h-9 max-w-80 rounded-md border bg-background px-3 text-sm"
                  value={activeRunId ?? ""}
                  onChange={(event) => setActiveRunId(event.target.value)}
                >
                  {(runs.data?.data ?? []).map((candidate, index) => (
                    <option key={candidate.id} value={candidate.id}>
                      批次 {runs.data!.data.length - index} ·{" "}
                      {candidate.provider}/{candidate.model}
                    </option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border bg-border md:grid-cols-4 xl:grid-cols-7">
                {[
                  [
                    "来源",
                    current.source_type === "model" ? "模型解题" : "答案文档",
                  ],
                  ["提供者", current.provider],
                  ["模型", current.model],
                  ["模型耗时", formatMs(current.timing.modelMs)],
                  ["总耗时", formatMs(current.timing.totalElapsedMs)],
                  [
                    "草稿总分",
                    items.data?.length ? `${draftTotalScore} 分` : "—",
                  ],
                  [
                    "平均置信度",
                    averageConfidence === null
                      ? "—"
                      : `${Math.round(averageConfidence * 100)}%`,
                  ],
                ].map(([label, value]) => (
                  <div key={label} className="min-w-0 bg-background px-4 py-3">
                    <div className="text-muted-foreground text-xs">{label}</div>
                    <div className="mt-1 truncate font-medium text-sm">
                      {value}
                    </div>
                  </div>
                ))}
              </div>
              {current.error_message && (
                <div className="rounded-xl border border-destructive px-4 py-3 text-destructive text-sm">
                  {current.error_message}
                </div>
              )}
              {current.timing.fallbackUsed && (
                <div className="rounded-xl border border-amber-200 px-4 py-3 text-amber-700 text-sm">
                  主通道暂时不可用，本批答案已自动切换备用通道完成
                </div>
              )}
            </section>
          )}

          {current && ["queued", "running"].includes(current.status) ? (
            <div className="flex min-h-48 items-center justify-center gap-2 rounded-2xl border bg-card text-muted-foreground text-sm shadow-card">
              <Loader2 className="animate-spin" />
              正在准备标准答案与评分准则
            </div>
          ) : items.data?.length ? (
            <>
              <section className="overflow-hidden rounded-2xl border bg-card shadow-card">
                <div className="border-b px-5 py-4">
                  <h2 className="font-semibold text-sm">答案匹配与评分准则</h2>
                  <div className="text-muted-foreground text-xs">
                    冲突和未匹配项不会进入答案版本。点击条目行展开编辑
                  </div>
                </div>
                <div className="divide-y">
                  {(items.data ?? []).map((item) => (
                    <AnswerItemRow
                      key={item.id}
                      item={item}
                      draft={
                        drafts[item.id] ?? {
                          questionId: item.question_id ?? "unassigned",
                          answerText: item.answer_text,
                          maxScore: String(item.max_score),
                          rubricText: item.rubric_text ?? "",
                          scoringPoints: item.scoring_points,
                        }
                      }
                      questions={confirmedQuestions}
                      locked={Boolean(current?.confirmed_at)}
                      error={saveErrors[item.id]}
                      onChange={(patch) => updateDraft(item.id, patch)}
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
                {current?.confirmed_at ? (
                  <div className="flex items-center gap-2">
                    <Tag variant="indigo">第 2 步 · 发布</Tag>
                    <Button
                      disabled={!draftRevisions.length || publish.isPending}
                      onClick={() => publish.mutate()}
                      className="bg-gradient-primary text-white hover:opacity-90"
                    >
                      {publish.isPending ? (
                        <Loader2 className="animate-spin" />
                      ) : (
                        <BookCheck />
                      )}
                      发布 {draftRevisions.length} 个待发布版本
                    </Button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <Tag variant="indigo">第 1 步 · 确认</Tag>
                    <Button
                      disabled={
                        !completed || confirm.isPending || dirtyIds.size > 0
                      }
                      onClick={() => confirm.mutate()}
                      className="bg-gradient-primary text-white hover:opacity-90"
                    >
                      {confirm.isPending ? (
                        <Loader2 className="animate-spin" />
                      ) : (
                        <Check />
                      )}
                      确认答案与评分准则
                    </Button>
                  </div>
                )}
              </div>
            </>
          ) : null}

          <section className="grid gap-4 rounded-2xl border bg-card p-5 shadow-card">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <History className="size-4 text-muted-foreground" />
                <h2 className="font-semibold text-sm">答案版本</h2>
                <Tag variant="indigo">{revisions.data?.count ?? 0}</Tag>
              </div>
            </div>
            <div className="overflow-hidden rounded-xl border">
              {(revisions.data?.data ?? []).length === 0 ? (
                <div className="px-4 py-8 text-center text-muted-foreground text-sm">
                  尚无答案版本
                </div>
              ) : (
                (revisions.data?.data ?? []).map((revision) => (
                  <div
                    key={revision.id}
                    className="grid gap-3 border-b px-4 py-4 last:border-b-0 md:grid-cols-[120px_minmax(0,1fr)_auto] md:items-start"
                  >
                    <div>
                      <div className="font-medium">
                        第 {revision.question_key} 题
                      </div>
                      <div className="mt-1 text-muted-foreground text-xs">
                        版本 {revision.revision_number}
                      </div>
                    </div>
                    <div className="min-w-0">
                      <div className="line-clamp-2 text-sm">
                        {revision.answer_text}
                      </div>
                      <div className="mt-1 text-muted-foreground text-xs">
                        {revision.source_provider}/{revision.source_model} ·
                        满分 {revision.max_score} ·{" "}
                        {revision.scoring_points.length} 个评分点
                      </div>
                    </div>
                    <Tag
                      variant={
                        revision.status === "published" ? "mint" : "amber"
                      }
                    >
                      {revision.status === "published"
                        ? "已发布锁定"
                        : "待发布"}
                    </Tag>
                  </div>
                ))
              )}
            </div>
          </section>
        </>
      )}
    </div>
  )
}
