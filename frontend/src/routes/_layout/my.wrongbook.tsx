import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  BookMarked,
  Printer,
  RotateCcw,
  SlidersHorizontal,
  UserRound,
} from "lucide-react"
import type React from "react"
import { useEffect, useState } from "react"
import type { WrongbookEntryListItem } from "@/client"
import { ApiError, StudentsService } from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHead } from "@/components/Common/PageHead"
import { Tag } from "@/components/Common/Tag"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { fetchWrongbookEntryImageBlob } from "@/lib/submission-media"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout/my/wrongbook")({
  component: MyWrongbookPage,
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

  if (isError) return null
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
    </div>
  )
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
      {rows.map((row) => (
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
          </div>
          <p className="mt-1 text-muted-foreground text-xs">
            做过 {row.attempts ?? 0} 题 · 错 {row.wrong_count ?? 0} 题
            {row.last_reviewed_at
              ? ` · 最近复习 ${formatDate(row.last_reviewed_at)}`
              : " · 还没复习过"}
          </p>
        </div>
      ))}
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
              {formatScore(row.score)} / {formatScore(row.max_score)} 分
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

function MyWrongbookPage() {
  const [subject, setSubject] = useState<string | null>(null)
  const [knowledgePoint, setKnowledgePoint] = useState<string | null>(null)
  const [tab, setTab] = useState<WrongbookTab>("entries")
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [reviewDone, setReviewDone] = useState(false)
  const query = useQuery({
    queryKey: ["my-wrongbook", subject, knowledgePoint],
    queryFn: () =>
      StudentsService.readMyWrongbook({
        subject: subject ?? undefined,
        knowledgePoint: knowledgePoint ?? undefined,
      }),
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
                <EntryCard key={entry.entry_id} entry={entry} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
