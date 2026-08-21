import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router"
import {
  BookMarked,
  FileText,
  FolderPlus,
  Lightbulb,
  Loader2,
  Network,
  Printer,
  RotateCcw,
  SlidersHorizontal,
  Trash2,
  UserRound,
} from "lucide-react"
import type React from "react"
import { useEffect, useState } from "react"
import { z } from "zod"
import type {
  WrongbookEntriesPublic,
  WrongbookEntryListItem,
  WrongQuestionErrorReason,
} from "@/client"
import { ApiError, StudentsService } from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHead } from "@/components/Common/PageHead"
import { Tag } from "@/components/Common/Tag"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import useCustomToast from "@/hooks/useCustomToast"
import { fetchWrongbookEntryImageBlob } from "@/lib/submission-media"
import { cn } from "@/lib/utils"
import { workflowApi } from "@/lib/workflow-api"

const searchSchema = z.object({
  /** 知识点过滤：知识图谱点某个知识点进来时带上 */
  kp: z.string().optional().catch(undefined),
})

export const Route = createFileRoute("/_layout/my/wrongbook")({
  component: MyWrongbookPage,
  validateSearch: searchSchema,
  head: () => ({ meta: [{ title: "我的错题本 - 点凡阅卷" }] }),
})

function formatScore(value: number | null | undefined): string {
  if (value == null) return "--"
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function formatDate(value: string | null | undefined): string | null {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
  })
}

function formatDateTime(value: string | null | undefined): string | null {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

const ERROR_REASONS: Array<{
  value: WrongQuestionErrorReason
  label: string
}> = [
  { value: "concept", label: "概念不清" },
  { value: "calculation", label: "计算失误" },
  { value: "reading", label: "审题不清" },
  { value: "unknown_knowledge", label: "完全不会" },
]

const ERROR_REASON_LABELS = Object.fromEntries(
  ERROR_REASONS.map((item) => [item.value, item.label]),
) as Record<WrongQuestionErrorReason, string>

/** 答题图：错题本自带留存图，考试被删也还在。 */
function EntryImage({ entryId, label }: { entryId: string; label: string }) {
  const [contentUrl, setContentUrl] = useState<string | null>(null)
  const { data, isPending, isError } = useQuery({
    queryKey: ["wrongbook-entry-image", entryId],
    queryFn: () => fetchWrongbookEntryImageBlob(entryId),
    staleTime: Number.POSITIVE_INFINITY,
  })

  useEffect(() => {
    if (!data) return
    const url = URL.createObjectURL(data)
    setContentUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [data])

  if (isError) {
    return (
      <div className="flex h-24 w-full max-w-md items-center justify-center rounded-lg border border-dashed text-muted-foreground text-xs">
        答题图暂不可用
      </div>
    )
  }
  if (isPending || !contentUrl) {
    return <Skeleton className="h-24 w-full max-w-md rounded-lg" />
  }
  return (
    <img
      src={contentUrl}
      alt={`${label} 我的作答`}
      className="max-h-52 w-auto max-w-full rounded-lg border bg-white object-contain"
    />
  )
}

/** 错因快选：点选即存，再点已选中的可清除。 */
function ErrorReasonPicker({
  entryId,
  value,
}: {
  entryId: string
  value: WrongQuestionErrorReason | null | undefined
}) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const mutation = useMutation({
    mutationFn: (reason: WrongQuestionErrorReason | null) =>
      StudentsService.updateMyWrongbookEntry({
        entryId,
        requestBody: { error_reason: reason },
      }),
    onSuccess: (_data, reason) => {
      queryClient.invalidateQueries({ queryKey: ["wrongbook-entry", entryId] })
      queryClient.invalidateQueries({ queryKey: ["my-wrongbook"] })
      queryClient.invalidateQueries({ queryKey: ["my-wrongbook-due"] })
      showSuccessToast(reason ? "已记下这道题的错因" : "已清除这道题的错因标注")
    },
    onError: () => showErrorToast("错因没保存成功，请再点一次"),
  })

  return (
    <section>
      <h5 className="mb-2 font-medium text-muted-foreground text-xs">
        这道题为什么错（选一个，学习建议会更准）
      </h5>
      <div className="flex flex-wrap gap-2">
        {ERROR_REASONS.map((item) => {
          const selected = value === item.value
          return (
            <Button
              key={item.value}
              variant={selected ? "secondary" : "outline"}
              size="sm"
              disabled={mutation.isPending}
              title={selected ? "再点一次清除" : undefined}
              onClick={() => mutation.mutate(selected ? null : item.value)}
            >
              {item.label}
            </Button>
          )
        })}
      </div>
    </section>
  )
}

function EntryDetail({ entryId }: { entryId: string }) {
  const query = useQuery({
    queryKey: ["wrongbook-entry", entryId],
    queryFn: () => StudentsService.readMyWrongbookEntry({ entryId }),
  })

  if (query.isPending) {
    return <Skeleton className="h-40 w-full rounded-lg" />
  }
  if (query.isError || !query.data) {
    return <p className="text-destructive text-sm">这道题暂时打不开</p>
  }
  const entry = query.data
  return (
    <div className="flex flex-col gap-4 border-t pt-4">
      {entry.question_text && (
        <section>
          <h5 className="mb-1 font-medium text-muted-foreground text-xs">
            题目
          </h5>
          <p className="whitespace-pre-wrap text-sm leading-6">
            {entry.question_text}
          </p>
        </section>
      )}
      {entry.has_image && (
        <section>
          <h5 className="mb-2 font-medium text-muted-foreground text-xs">
            我的作答
          </h5>
          <EntryImage entryId={entry.entry_id} label={entry.question_label} />
        </section>
      )}
      {entry.student_answer_text && (
        <section>
          <h5 className="mb-1 font-medium text-muted-foreground text-xs">
            识别到的作答
          </h5>
          <p className="whitespace-pre-wrap rounded-lg bg-muted/50 p-3 text-sm leading-6">
            {entry.student_answer_text}
          </p>
        </section>
      )}
      {(entry.missed_points ?? []).length > 0 && (
        <section>
          <h5 className="mb-2 font-medium text-muted-foreground text-xs">
            这道题丢在哪
          </h5>
          <ul className="flex flex-col gap-2">
            {(entry.missed_points ?? []).map((point, index) => {
              const item = point as {
                point?: string
                reason?: string
                points?: number
              }
              return (
                <li
                  key={`${item.point ?? "point"}-${index}`}
                  className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 text-sm dark:border-amber-900 dark:bg-amber-950/30"
                >
                  <span className="font-medium">
                    {item.point || "未答到的要点"}
                  </span>
                  {item.points != null && (
                    <span className="ml-2 text-muted-foreground text-xs">
                      -{formatScore(item.points)} 分
                    </span>
                  )}
                  {item.reason && (
                    <p className="mt-1 text-muted-foreground leading-6">
                      {item.reason}
                    </p>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      )}
      {entry.standard_answer_text && (
        <section>
          <h5 className="mb-1 font-medium text-muted-foreground text-xs">
            参考答案
          </h5>
          <p className="whitespace-pre-wrap rounded-lg bg-muted/50 p-3 text-sm leading-6">
            {entry.standard_answer_text}
          </p>
        </section>
      )}
      {entry.teacher_comment && (
        <section>
          <h5 className="mb-1 font-medium text-muted-foreground text-xs">
            老师评语
          </h5>
          <p className="whitespace-pre-wrap text-sm leading-6">
            {entry.teacher_comment}
          </p>
        </section>
      )}
      <ErrorReasonPicker entryId={entry.entry_id} value={entry.error_reason} />
    </div>
  )
}

/** 后端错题集模型（生成 client 未更新，先用本地类型）。 */
type WrongbookCollectionPublic = {
  id: string
  name: string
  entry_count: number
  created_at: string
}

function EntryCard({
  entry,
  defaultOpen = false,
  footer,
}: {
  entry: WrongbookEntryListItem
  defaultOpen?: boolean
  footer?: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  const rate =
    entry.score != null && entry.max_score
      ? Math.round((entry.score / entry.max_score) * 100)
      : null
  const meta = [entry.subject, formatDate(entry.exam_date)].filter(Boolean)
  return (
    <div className="rounded-2xl bg-card p-5 shadow-card">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-semibold">{entry.question_label}</span>
        {entry.max_score != null ? (
          <>
            <span
              className={cn(
                "font-semibold",
                rate != null && rate < 40
                  ? "text-red-600 dark:text-red-400"
                  : "text-amber-600 dark:text-amber-400",
              )}
            >
              {formatScore(entry.score)}
            </span>
            <span className="text-muted-foreground text-sm">
              / {formatScore(entry.max_score)} 分
            </span>
          </>
        ) : (
          <span className="text-muted-foreground text-sm">未评分</span>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {(entry.review_count ?? 0) > 0 && (
            <Tag variant="neutral">复习 {entry.review_count} 次</Tag>
          )}
          {(entry.knowledge_point_names ?? []).map((name) => (
            <Tag key={name} variant="neutral">
              {name}
            </Tag>
          ))}
        </div>
      </div>
      <p className="mt-1 text-muted-foreground text-xs">
        {[entry.exam_title, ...meta].join(" · ")}
        {entry.error_reason && (
          <span className="ml-2 text-amber-600 dark:text-amber-400">
            错因 · {ERROR_REASON_LABELS[entry.error_reason]}
          </span>
        )}
      </p>
      {!defaultOpen && (
        <div className="mt-3">
          <Button
            variant="ghost"
            size="sm"
            className="px-0"
            onClick={() => setOpen((value) => !value)}
          >
            {open ? "收起" : "看看为什么错"}
          </Button>
        </div>
      )}
      {open && <EntryDetail entryId={entry.entry_id} />}
      {footer}
    </div>
  )
}

const REVIEW_CHOICES: Array<{
  result: "again" | "hard" | "good" | "easy"
  label: string
}> = [
  { result: "again", label: "还是不会" },
  { result: "hard", label: "有点吃力" },
  { result: "good", label: "会了" },
  { result: "easy", label: "很轻松" },
]

/** 复习面板：一次只看一题，点完自动进入下一题。只问「还会不会」，不让学生重做。 */
function ReviewPanel({
  onExit,
  onDone,
}: {
  onExit: () => void
  onDone: () => void
}) {
  const queryClient = useQueryClient()
  const [index, setIndex] = useState(0)
  const query = useQuery({
    queryKey: ["my-wrongbook-due"],
    queryFn: () => StudentsService.readMyDueReviews({ limit: 20 }),
  })
  const mutation = useMutation({
    mutationFn: ({
      entryId,
      result,
    }: {
      entryId: string
      result: "again" | "hard" | "good" | "easy"
    }) =>
      StudentsService.reviewMyWrongbookEntry({
        entryId,
        requestBody: { result },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-wrongbook"] })
      queryClient.invalidateQueries({ queryKey: ["my-wrongbook-mastery"] })
      setIndex((value) => value + 1)
    },
  })

  const entries = query.data?.data ?? []
  const current = entries[index]
  const finished = !query.isPending && !current

  // 队列做完就退出专注模式，把页签还给学生，否则做完了只能困在复习页里
  useEffect(() => {
    if (finished) onDone()
  }, [finished, onDone])

  if (query.isPending) return <Skeleton className="h-64 w-full rounded-2xl" />

  if (!current) {
    return (
      <div className="rounded-2xl bg-card p-8 text-center shadow-card">
        <p className="font-semibold">今天的复习做完了</p>
        <p className="mt-1 text-muted-foreground text-sm">
          {entries.length > 0
            ? `复习了 ${entries.length} 题，明天会安排下一批`
            : "暂时没有到期的错题，等下次考试出分后再来"}
        </p>
        <Button className="mt-4" onClick={onExit}>
          返回错题本
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-muted-foreground text-sm">
          第 {index + 1} / {entries.length} 题
        </p>
        <Button variant="ghost" size="sm" onClick={onExit}>
          稍后再练
        </Button>
      </div>
      <EntryCard key={current.entry_id} entry={current} defaultOpen />
      {/* 评分按钮常驻屏幕底部：手机上题目很长，否则每题都要滑到底才能点 */}
      <div className="-mx-5 sticky bottom-16 border-t bg-background/95 px-5 py-3 backdrop-blur md:-mx-6 md:bottom-0 md:px-6">
        <div className="flex gap-2">
          {REVIEW_CHOICES.map((choice) => (
            <Button
              key={choice.result}
              variant={choice.result === "good" ? "default" : "outline"}
              size="sm"
              className="flex-1 px-1"
              disabled={mutation.isPending}
              onClick={() =>
                mutation.mutate({
                  entryId: current.entry_id,
                  result: choice.result,
                })
              }
            >
              {choice.label}
            </Button>
          ))}
        </div>
      </div>
    </div>
  )
}

/** 学习建议卡：学生主动点「生成」才调接口（模型分析较慢），结果含总体建议、重点知识点和一周安排。 */
function LearningAdviceCard() {
  const [requested, setRequested] = useState(false)
  // generation 递增强制重新生成（绕过 query 缓存）
  const [generation, setGeneration] = useState(0)
  const query = useQuery({
    queryKey: ["my-learning-advice", generation],
    queryFn: () => StudentsService.readMyLearningAdvice(),
    enabled: requested,
    retry: false,
  })

  const regenerate = () => {
    setRequested(true)
    setGeneration((value) => value + 1)
  }

  return (
    <div className="rounded-2xl bg-card p-5 shadow-card print:hidden">
      <div className="flex items-center gap-2">
        <Lightbulb className="size-4 text-muted-foreground" />
        <p className="font-semibold">学习建议</p>
      </div>

      {!requested ? (
        <>
          <p className="mt-2 text-muted-foreground text-sm leading-6">
            根据你错题本里的记录，整理出薄弱环节和接下来一周的练习安排。
          </p>
          <Button className="mt-3" size="sm" onClick={regenerate}>
            生成我的学习建议
          </Button>
        </>
      ) : query.isPending ? (
        <p className="mt-3 flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="size-4 animate-spin" />
          正在分析你的错题记录，可能需要半分钟…
        </p>
      ) : query.isError || !query.data ? (
        <>
          <p className="mt-2 text-muted-foreground text-sm">
            这次没生成成功，等下再试试。
          </p>
          <Button
            className="mt-3"
            variant="ghost"
            size="sm"
            onClick={regenerate}
          >
            重新生成
          </Button>
        </>
      ) : !query.data.has_data ? (
        <p className="mt-2 text-muted-foreground text-sm leading-6">
          还没有错题记录，考完一场试再来看看。
        </p>
      ) : (
        <div className="mt-3 flex flex-col gap-4">
          {query.data.overall && (
            <p className="whitespace-pre-wrap text-sm leading-6">
              {query.data.overall}
            </p>
          )}
          {(query.data.focus_points ?? []).length > 0 && (
            <section>
              <h5 className="mb-2 font-medium text-muted-foreground text-xs">
                最该补的几块
              </h5>
              <ul className="flex flex-col gap-2">
                {(query.data.focus_points ?? []).map((point) => (
                  <li
                    key={point.knowledge_point}
                    className="rounded-lg border p-3"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Tag variant="neutral">{point.knowledge_point}</Tag>
                      {point.times != null && (
                        <span className="text-muted-foreground text-xs">
                          错了 {point.times} 次
                        </span>
                      )}
                      <Link
                        to="/my/wrongbook-sheet"
                        search={{
                          kps: point.knowledge_point,
                          mode: "variants",
                          range: "90d",
                          limit: 5,
                        }}
                        className="ml-auto text-primary text-xs hover:underline"
                      >
                        生成变式练习 →
                      </Link>
                    </div>
                    <p className="mt-1.5 text-sm leading-6">{point.advice}</p>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {(query.data.weekly_plan ?? []).length > 0 && (
            <section>
              <h5 className="mb-2 font-medium text-muted-foreground text-xs">
                这一周怎么练
              </h5>
              <ol className="flex flex-col gap-1.5">
                {(query.data.weekly_plan ?? []).map((item, index) => (
                  <li
                    key={`${index}-${item.slice(0, 12)}`}
                    className="text-sm leading-6"
                  >
                    <span className="mr-1.5 font-medium">{index + 1}.</span>
                    {item}
                  </li>
                ))}
              </ol>
            </section>
          )}
          <div className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground text-xs">
              {formatDateTime(query.data.generated_at)
                ? `生成于 ${formatDateTime(query.data.generated_at)}`
                : ""}
            </span>
            <Button
              variant="ghost"
              size="sm"
              className="px-0"
              onClick={regenerate}
            >
              重新生成
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function MasterySection() {
  const query = useQuery({
    queryKey: ["my-wrongbook-mastery"],
    queryFn: () => StudentsService.readMyMastery(),
  })
  if (query.isPending) return <Skeleton className="h-32 w-full rounded-2xl" />
  const rows = query.data?.data ?? []
  if (rows.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        题目还没有标注知识点，暂时统计不出薄弱环节。
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-3">
      {rows.map((row) => {
        const enough = (row.attempts ?? 0) >= 3
        return (
          <div
            key={`${row.subject ?? ""}-${row.knowledge_point_name}`}
            className="rounded-2xl bg-card p-4 shadow-card"
          >
            <div className="flex items-baseline gap-2">
              <span className="font-medium">{row.knowledge_point_name}</span>
              {row.subject && (
                <span className="text-muted-foreground text-xs">
                  {row.subject}
                </span>
              )}
              {enough ? (
                <span
                  className={cn(
                    "ml-auto font-semibold",
                    (row.wrong_rate ?? 0) >= 60
                      ? "text-red-600 dark:text-red-400"
                      : "text-amber-600 dark:text-amber-400",
                  )}
                >
                  错 {row.wrong_rate ?? 0}%
                </span>
              ) : (
                <span className="ml-auto text-muted-foreground text-xs">
                  样本不足
                </span>
              )}
            </div>
            <p className="mt-1 text-muted-foreground text-xs">
              做过 {row.attempts ?? 0} 题 · 错 {row.wrong_count ?? 0} 题
              {row.last_reviewed_at
                ? ` · 最近复习 ${formatDate(row.last_reviewed_at)}`
                : " · 还没复习过"}
            </p>
          </div>
        )
      })}
    </div>
  )
}

function CramSection({ subject }: { subject: string | null }) {
  const query = useQuery({
    queryKey: ["my-wrongbook-cram", subject],
    queryFn: () =>
      StudentsService.readMyCramList({
        subject: subject ?? undefined,
        limit: 30,
      }),
  })
  if (query.isPending) return <Skeleton className="h-32 w-full rounded-2xl" />
  const rows = query.data?.data ?? []
  if (rows.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">暂时没有需要突击的错题。</p>
    )
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between print:hidden">
        <p className="text-muted-foreground text-sm">
          按薄弱程度排序的 {rows.length} 题，可以打印出来做
        </p>
        <Button variant="outline" size="sm" onClick={() => window.print()}>
          <Printer className="mr-1.5 size-4" />
          打印清单
        </Button>
      </div>
      <ol className="flex flex-col gap-2">
        {rows.map((row, order) => (
          <li
            key={row.entry_id}
            className="rounded-xl border p-3 text-sm leading-6"
          >
            <span className="font-medium">
              {order + 1}. {row.exam_title} {row.question_label}
            </span>
            <span className="ml-2 text-muted-foreground">
              {row.max_score != null
                ? `${formatScore(row.score)} / ${formatScore(row.max_score)} 分`
                : "未评分"}
            </span>
            {(row.knowledge_point_names ?? []).length > 0 && (
              <span className="ml-2 text-muted-foreground text-xs">
                {(row.knowledge_point_names ?? []).join("、")}
              </span>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}

type WrongbookTab = "entries" | "review" | "mastery" | "cram"

const SHEET_RANGES = [
  { value: "30d", label: "近30天" },
  { value: "90d", label: "近90天" },
  { value: "all", label: "全部" },
] as const

const SHEET_LIMITS = [5, 10, 20] as const

/** 生成错题卷：选知识点、时间范围和题数，跳转到可打印的练习卷页。 */
function GenerateSheetDialog({
  knowledgePoints,
}: {
  knowledgePoints: string[]
}) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [range, setRange] = useState<"30d" | "90d" | "all">("90d")
  const [limit, setLimit] = useState<number>(10)

  const toggle = (name: string) =>
    setSelected((value) =>
      value.includes(name)
        ? value.filter((item) => item !== name)
        : [...value, name],
    )

  const generate = () => {
    setOpen(false)
    navigate({
      to: "/my/wrongbook-sheet",
      search: {
        kps: selected.length > 0 ? selected.join(",") : undefined,
        range,
        limit,
      },
    })
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost">
          <FileText className="size-4" />
          生成错题卷
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>生成错题练习卷</DialogTitle>
          <DialogDescription>
            把错题按知识点整理成一张 A4 练习卷，打印出来线下做，卷尾附参考答案。
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-5 py-2">
          <section>
            <h5 className="mb-2 font-medium text-muted-foreground text-xs">
              知识点（不选就是全部）
            </h5>
            {knowledgePoints.length === 0 ? (
              <p className="text-muted-foreground text-sm leading-6">
                错题还没有标注知识点，等老师批改时在题目上标好知识点后再来生成。
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {knowledgePoints.map((name) => (
                  <Button
                    key={name}
                    variant={selected.includes(name) ? "secondary" : "outline"}
                    size="sm"
                    onClick={() => toggle(name)}
                  >
                    {name}
                  </Button>
                ))}
              </div>
            )}
          </section>
          <section>
            <h5 className="mb-2 font-medium text-muted-foreground text-xs">
              时间范围
            </h5>
            <div className="flex gap-2">
              {SHEET_RANGES.map((item) => (
                <Button
                  key={item.value}
                  variant={range === item.value ? "secondary" : "outline"}
                  size="sm"
                  onClick={() => setRange(item.value)}
                >
                  {item.label}
                </Button>
              ))}
            </div>
          </section>
          <section>
            <h5 className="mb-2 font-medium text-muted-foreground text-xs">
              题数上限
            </h5>
            <div className="flex gap-2">
              {SHEET_LIMITS.map((value) => (
                <Button
                  key={value}
                  variant={limit === value ? "secondary" : "outline"}
                  size="sm"
                  onClick={() => setLimit(value)}
                >
                  {value} 题
                </Button>
              ))}
            </div>
          </section>
        </div>
        <DialogFooter>
          <Button onClick={generate}>生成错题卷</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function MyWrongbookPage() {
  const { kp } = Route.useSearch()
  const [subject, setSubject] = useState<string | null>(null)
  const [knowledgePoint, setKnowledgePoint] = useState<string | null>(
    kp ?? null,
  )
  const [tab, setTab] = useState<WrongbookTab>("entries")
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [reviewDone, setReviewDone] = useState(false)

  // 从知识图谱带 kp 跳进来时同步过滤器；组件复用（连续点不同知识点）也要生效
  useEffect(() => {
    if (kp) setKnowledgePoint(kp)
  }, [kp])
  // 自定义错题集：选中某个集时列表只显示该集成员
  const [collectionId, setCollectionId] = useState<string | null>(null)
  const [creatingCollection, setCreatingCollection] = useState(false)
  const [collectionName, setCollectionName] = useState("")
  const [confirmDeleteCollection, setConfirmDeleteCollection] = useState(false)
  const [confirmDeleteEntry, setConfirmDeleteEntry] = useState<string | null>(
    null,
  )
  const queryClient = useQueryClient()
  const collectionsQuery = useQuery({
    queryKey: ["my-wrongbook-collections"],
    queryFn: () =>
      workflowApi<WrongbookCollectionPublic[]>(
        "/students/me/wrongbook/collections",
      ),
  })
  const collections = collectionsQuery.data ?? []
  const invalidateWrongbook = () => {
    queryClient.invalidateQueries({ queryKey: ["my-wrongbook"] })
    queryClient.invalidateQueries({ queryKey: ["my-wrongbook-collections"] })
  }
  const createCollection = useMutation({
    mutationFn: () =>
      workflowApi("/students/me/wrongbook/collections", {
        method: "POST",
        body: JSON.stringify({ name: collectionName.trim() }),
      }),
    onSuccess: () => {
      setCollectionName("")
      setCreatingCollection(false)
      invalidateWrongbook()
    },
  })
  const deleteCollection = useMutation({
    mutationFn: (id: string) =>
      workflowApi(`/students/me/wrongbook/collections/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      setCollectionId(null)
      setConfirmDeleteCollection(false)
      invalidateWrongbook()
    },
  })
  const deleteEntry = useMutation({
    mutationFn: (entryId: string) =>
      workflowApi(`/students/me/wrongbook/entries/${entryId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      setConfirmDeleteEntry(null)
      invalidateWrongbook()
    },
  })
  const assignEntry = useMutation({
    mutationFn: ({
      entryId,
      collection,
    }: {
      entryId: string
      collection: string
    }) =>
      workflowApi(`/students/me/wrongbook/collections/${collection}/entries`, {
        method: "POST",
        body: JSON.stringify({ entry_id: entryId }),
      }),
    onSuccess: invalidateWrongbook,
  })

  const query = useQuery({
    queryKey: ["my-wrongbook", subject, knowledgePoint, collectionId],
    queryFn: () => {
      const params = new URLSearchParams()
      if (subject) params.set("subject", subject)
      if (knowledgePoint) params.set("knowledge_point", knowledgePoint)
      if (collectionId) params.set("collection_id", collectionId)
      const suffix = params.size ? `?${params}` : ""
      return workflowApi<WrongbookEntriesPublic>(
        `/students/me/wrongbook/entries${suffix}`,
      )
    },
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 3,
  })
  const dueQuery = useQuery({
    queryKey: ["my-wrongbook-due"],
    queryFn: () => StudentsService.readMyDueReviews({ limit: 20 }),
    retry: false,
  })

  const profileQuery = useQuery({
    queryKey: ["my-learner-profile"],
    queryFn: () => StudentsService.readMyLearnerProfile(),
    retry: false,
  })

  const isUnbound =
    query.error instanceof ApiError && query.error.status === 404
  const entries = query.data?.data ?? []
  const subjects = query.data?.subjects ?? []
  const knowledgePoints = query.data?.knowledge_points ?? []
  const dueCount = dueQuery.data?.count ?? 0

  // 复习是专注模式：手机屏幕小，标题、身份行和页签在做题时都是噪声。
  // 队列做完后退出专注，让学生能直接去看薄弱知识点或考前清单。
  const focused = tab === "review" && !reviewDone

  return (
    <div className="flex flex-col gap-6">
      {!focused && (
        <PageHead
          title="我的错题本"
          subtitle="每次考试出分后自动收进来，不用自己录"
          actions={
            <>
              <Button asChild variant="ghost">
                <Link to="/my/knowledge">
                  <Network className="size-4" />
                  知识图谱
                </Link>
              </Button>
              <GenerateSheetDialog knowledgePoints={knowledgePoints} />
            </>
          }
        />
      )}

      {!focused &&
        profileQuery.data &&
        (profileQuery.data.enrollments ?? []).length > 0 && (
          <p className="text-muted-foreground text-xs">
            {(profileQuery.data.enrollments ?? [])
              .map((item) =>
                [item.org_name, item.class_name].filter(Boolean).join(" "),
              )
              .filter(Boolean)
              .join(" → ")}
            {" · 累计 "}
            {profileQuery.data.entry_count ?? 0} 题，其中错题{" "}
            {profileQuery.data.wrong_count ?? 0} 题
          </p>
        )}

      {!isUnbound && !query.isPending && (
        <>
          {!focused && <LearningAdviceCard />}
          {dueCount > 0 && tab !== "review" && (
            <button
              type="button"
              onClick={() => {
                setReviewDone(false)
                setTab("review")
              }}
              className="flex items-center gap-4 rounded-2xl bg-card p-5 text-left shadow-card transition-shadow hover:shadow-card-lg print:hidden"
            >
              <div className="min-w-0 flex-1">
                <p className="font-semibold">今天要复习 {dueCount} 题</p>
                <p className="mt-0.5 text-muted-foreground text-sm">
                  每题只用回答「还会不会」，几分钟就能过一遍
                </p>
              </div>
              <RotateCcw className="size-5 shrink-0 text-muted-foreground" />
            </button>
          )}
          {!focused && (
            <div className="-mx-1 flex gap-1 overflow-x-auto px-1 print:hidden">
              {(
                [
                  ["entries", "全部错题"],
                  ["review", "今天复习"],
                  ["mastery", "薄弱知识点"],
                  ["cram", "考前清单"],
                ] as Array<[WrongbookTab, string]>
              ).map(([value, label]) => (
                <Button
                  key={value}
                  variant={tab === value ? "secondary" : "ghost"}
                  size="sm"
                  className="shrink-0"
                  onClick={() => {
                    if (value === "review") setReviewDone(false)
                    setTab(value)
                  }}
                >
                  {label}
                  {value === "review" && dueCount > 0 ? ` (${dueCount})` : ""}
                </Button>
              ))}
            </div>
          )}
        </>
      )}

      {tab === "review" && !isUnbound && (
        <ReviewPanel
          onExit={() => setTab("entries")}
          onDone={() => setReviewDone(true)}
        />
      )}
      {tab === "mastery" && !isUnbound && <MasterySection />}
      {tab === "cram" && !isUnbound && <CramSection subject={subject} />}

      {tab !== "entries" && !isUnbound ? null : query.isPending ? (
        <div className="flex flex-col gap-4">
          {["s1", "s2", "s3"].map((key) => (
            <Skeleton key={key} className="h-28 rounded-2xl" />
          ))}
        </div>
      ) : isUnbound ? (
        <EmptyState
          icon={UserRound}
          title="账号未绑定学生档案"
          description="请联系老师将你的账号绑定到班级学生档案后查看错题本"
        />
      ) : query.isError ? (
        <p className="text-destructive text-sm">
          错题本加载失败：{String(query.error)}
        </p>
      ) : (
        <>
          {(subjects.length > 0 || knowledgePoints.length > 0) && (
            <div className="flex flex-col gap-3">
              {/* 手机屏幕小，筛选默认收起，别把第一道错题挤出首屏 */}
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="px-0"
                  onClick={() => setFiltersOpen((value) => !value)}
                >
                  <SlidersHorizontal className="mr-1.5 size-4" />
                  {filtersOpen ? "收起筛选" : "筛选"}
                </Button>
                {(subject || knowledgePoint) && (
                  <>
                    <span className="text-muted-foreground text-xs">
                      {[subject, knowledgePoint].filter(Boolean).join(" · ")}
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setSubject(null)
                        setKnowledgePoint(null)
                      }}
                    >
                      清除
                    </Button>
                  </>
                )}
              </div>
              {filtersOpen && (
                <div className="flex flex-col gap-3">
                  {subjects.length > 0 && (
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-muted-foreground text-xs">
                        学科
                      </span>
                      <Button
                        variant={subject ? "ghost" : "secondary"}
                        size="sm"
                        onClick={() => setSubject(null)}
                      >
                        全部
                      </Button>
                      {subjects.map((name) => (
                        <Button
                          key={name}
                          variant={subject === name ? "secondary" : "ghost"}
                          size="sm"
                          onClick={() => setSubject(name)}
                        >
                          {name}
                        </Button>
                      ))}
                    </div>
                  )}
                  {knowledgePoints.length > 0 && (
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-muted-foreground text-xs">
                        知识点
                      </span>
                      <Button
                        variant={knowledgePoint ? "ghost" : "secondary"}
                        size="sm"
                        onClick={() => setKnowledgePoint(null)}
                      >
                        全部
                      </Button>
                      {knowledgePoints.map((name) => (
                        <Button
                          key={name}
                          variant={
                            knowledgePoint === name ? "secondary" : "ghost"
                          }
                          size="sm"
                          onClick={() => setKnowledgePoint(name)}
                        >
                          {name}
                        </Button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* 自定义错题集：全部 + 各集 + 新建 */}
          <div
            className="flex flex-wrap items-center gap-2 print:hidden"
            data-testid="wrongbook-collections"
          >
            <span className="text-muted-foreground text-xs">错题集</span>
            <Button
              variant={collectionId === null ? "secondary" : "ghost"}
              size="sm"
              onClick={() => setCollectionId(null)}
            >
              全部
            </Button>
            {collections.map((collection) => (
              <Button
                key={collection.id}
                variant={collectionId === collection.id ? "secondary" : "ghost"}
                size="sm"
                data-testid={`collection-chip-${collection.name}`}
                onClick={() => setCollectionId(collection.id)}
              >
                {collection.name}（{collection.entry_count}）
              </Button>
            ))}
            {creatingCollection ? (
              <span className="flex items-center gap-1.5">
                <Input
                  data-testid="collection-name-input"
                  className="h-8 w-36"
                  placeholder="集名，如 计算专题"
                  value={collectionName}
                  onChange={(event) => setCollectionName(event.target.value)}
                />
                <Button
                  size="sm"
                  data-testid="collection-create-submit"
                  disabled={
                    !collectionName.trim() || createCollection.isPending
                  }
                  onClick={() => createCollection.mutate()}
                >
                  建立
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setCreatingCollection(false)
                    setCollectionName("")
                  }}
                >
                  取消
                </Button>
              </span>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                data-testid="collection-create-open"
                onClick={() => setCreatingCollection(true)}
              >
                <FolderPlus className="size-4" />
                新建错题集
              </Button>
            )}
            {collectionId &&
              (confirmDeleteCollection ? (
                <span className="flex items-center gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-destructive"
                    data-testid="collection-delete-confirm"
                    disabled={deleteCollection.isPending}
                    onClick={() => deleteCollection.mutate(collectionId)}
                  >
                    确认删除此集
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setConfirmDeleteCollection(false)}
                  >
                    取消
                  </Button>
                </span>
              ) : (
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-muted-foreground"
                  data-testid="collection-delete"
                  onClick={() => setConfirmDeleteCollection(true)}
                >
                  <Trash2 className="size-3.5" />
                  删除此集
                </Button>
              ))}
          </div>

          {entries.length === 0 ? (
            <EmptyState
              icon={BookMarked}
              title="还没有错题"
              description="老师发布成绩后，做错的题会自动收进这里，并标出丢分的地方"
            />
          ) : (
            <div className="flex flex-col gap-4">
              <p className="text-muted-foreground text-xs">
                共 {query.data?.count ?? entries.length} 道错题
              </p>
              {entries.map((entry) => (
                <EntryCard
                  key={entry.entry_id}
                  entry={entry}
                  footer={
                    <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3 print:hidden">
                      {collections.length > 0 && (
                        <select
                          className="h-8 rounded-md border bg-background px-2 text-xs"
                          data-testid={`assign-collection-${entry.entry_id}`}
                          value=""
                          onChange={(event) => {
                            const target = event.target.value
                            if (target) {
                              assignEntry.mutate({
                                entryId: entry.entry_id,
                                collection: target,
                              })
                            }
                            event.target.value = ""
                          }}
                        >
                          <option value="">移入错题集…</option>
                          {collections.map((collection) => (
                            <option key={collection.id} value={collection.id}>
                              {collection.name}
                            </option>
                          ))}
                        </select>
                      )}
                      {confirmDeleteEntry === entry.entry_id ? (
                        <span className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-destructive"
                            data-testid="entry-delete-confirm"
                            disabled={deleteEntry.isPending}
                            onClick={() => deleteEntry.mutate(entry.entry_id)}
                          >
                            确认删除
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setConfirmDeleteEntry(null)}
                          >
                            取消
                          </Button>
                        </span>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="ml-auto text-muted-foreground"
                          data-testid={`entry-delete-${entry.entry_id}`}
                          onClick={() => setConfirmDeleteEntry(entry.entry_id)}
                        >
                          <Trash2 className="size-4" />
                          删除
                        </Button>
                      )}
                    </div>
                  }
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
