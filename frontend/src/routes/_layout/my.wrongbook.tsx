import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { BookMarked, UserRound } from "lucide-react"
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

function EntryCard({ entry }: { entry: WrongbookEntryListItem }) {
  const [open, setOpen] = useState(false)
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
      {open && <EntryDetail entryId={entry.entry_id} />}
    </div>
  )
}

function MyWrongbookPage() {
  const [subject, setSubject] = useState<string | null>(null)
  const [knowledgePoint, setKnowledgePoint] = useState<string | null>(null)
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

  const isUnbound =
    query.error instanceof ApiError && query.error.status === 404
  const entries = query.data?.data ?? []
  const subjects = query.data?.subjects ?? []
  const knowledgePoints = query.data?.knowledge_points ?? []

  return (
    <div className="flex flex-col gap-6">
      <PageHead
        title="我的错题本"
        subtitle="每次考试出分后自动收进来，不用自己录"
      />

      {query.isPending ? (
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
              {subjects.length > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-muted-foreground text-xs">学科</span>
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
                  <span className="text-muted-foreground text-xs">知识点</span>
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
                      variant={knowledgePoint === name ? "secondary" : "ghost"}
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
