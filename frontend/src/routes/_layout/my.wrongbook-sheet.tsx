import { useQueries, useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft, BookOpenCheck, ClipboardList, Printer } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { z } from "zod"
import { StudentsService, type WrongbookEntryListItem } from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { Tag } from "@/components/Common/Tag"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { fetchWrongbookEntryImageBlob } from "@/lib/submission-media"

const searchSchema = z.object({
  kps: z.string().optional().catch(undefined),
  range: z.enum(["30d", "90d", "all"]).catch("90d"),
  limit: z.coerce.number().int().min(1).max(50).catch(10),
})

export const Route = createFileRoute("/_layout/my/wrongbook-sheet")({
  component: WrongbookSheetPage,
  validateSearch: searchSchema,
  head: () => ({ meta: [{ title: "我的错题练习卷 - 点凡阅卷" }] }),
})

const RANGE_LABELS: Record<string, string> = {
  "30d": "近30天",
  "90d": "近90天",
  all: "全部",
}

/** 客户端筛选：知识点取交集，时间范围看考试日期（缺日期用成绩发布日兜底）。 */
function filterEntries(
  entries: WrongbookEntryListItem[],
  kps: string[],
  range: string,
  limit: number,
): WrongbookEntryListItem[] {
  let result = entries
  if (kps.length > 0) {
    result = result.filter((entry) =>
      (entry.knowledge_point_names ?? []).some((name) => kps.includes(name)),
    )
  }
  if (range !== "all") {
    const cutoff = Date.now() - Number.parseInt(range, 10) * 24 * 60 * 60 * 1000
    result = result.filter((entry) => {
      const value = entry.exam_date ?? entry.released_at
      if (!value) return true
      const time = new Date(value).getTime()
      return Number.isNaN(time) || time >= cutoff
    })
  }
  return result.slice(0, limit)
}

/** 练习卷里的作答裁切图：blob 拉取，打印前等它加载完。 */
function SheetImage({ entryId, label }: { entryId: string; label: string }) {
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
      className="max-h-56 w-auto max-w-full rounded-lg border bg-white object-contain"
    />
  )
}

function scoringPointText(item: Record<string, unknown>): string {
  const value = item.point ?? item.text ?? item.content ?? item.description
  return typeof value === "string" && value.trim() ? value : "得分点"
}

function WrongbookSheetPage() {
  const search = Route.useSearch()
  const kps = useMemo(
    () => (search.kps ?? "").split(",").filter(Boolean),
    [search.kps],
  )

  const entriesQuery = useQuery({
    queryKey: ["my-wrongbook", "sheet"],
    queryFn: () =>
      StudentsService.readMyWrongbook({ wrongOnly: true, limit: 200 }),
  })
  const profileQuery = useQuery({
    queryKey: ["my-learner-profile"],
    queryFn: () => StudentsService.readMyLearnerProfile(),
    retry: false,
  })

  const selected = useMemo(
    () =>
      filterEntries(
        entriesQuery.data?.data ?? [],
        kps,
        search.range,
        search.limit,
      ),
    [entriesQuery.data, kps, search.range, search.limit],
  )

  const detailQueries = useQueries({
    queries: selected.map((entry) => ({
      queryKey: ["wrongbook-entry", entry.entry_id],
      queryFn: () =>
        StudentsService.readMyWrongbookEntry({
          entryId: entry.entry_id,
        }),
    })),
  })
  const detailsReady =
    detailQueries.length > 0 && detailQueries.every((query) => query.isSuccess)

  const generatedAt = useMemo(
    () =>
      new Date().toLocaleString("zh-CN", {
        year: "numeric",
        month: "long",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }),
    [],
  )

  if (entriesQuery.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="mx-auto h-[1100px] w-full max-w-[820px]" />
      </div>
    )
  }

  if (entriesQuery.isError) {
    return (
      <p className="text-destructive text-sm">
        错题卷加载失败：{String(entriesQuery.error)}
      </p>
    )
  }

  const studentName =
    profileQuery.data?.display_name ??
    profileQuery.data?.enrollments?.[0]?.student_name ??
    "我"
  const className = profileQuery.data?.enrollments?.[0]?.class_name
  const scopeText = [
    kps.length > 0 ? `知识点：${kps.join("、")}` : "知识点：全部",
    `时间：${RANGE_LABELS[search.range]}`,
  ].join(" · ")

  return (
    <div className="flex flex-col gap-6">
      {/* 操作条：屏幕专用，打印时隐藏 */}
      <div className="flex items-center justify-between print:hidden">
        <Link
          to="/my/wrongbook"
          className="inline-flex items-center gap-1 text-muted-foreground text-sm hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          返回错题本
        </Link>
        <Button variant="ghost" onClick={() => window.print()}>
          <Printer className="size-4" />
          打印
        </Button>
      </div>

      {selected.length === 0 ? (
        <EmptyState
          icon={ClipboardList}
          title="这个范围没有匹配的错题"
          description="返回错题本，换个知识点或时间范围再生成"
        />
      ) : (
        /* A4 练习卷 */
        <div className="mx-auto w-full max-w-[820px] rounded-2xl bg-card p-10 shadow-card-lg print:max-w-none print:rounded-none print:p-0 print:shadow-none">
          {/* 页眉 */}
          <div className="flex items-center gap-2 border-b pb-5">
            <span className="flex size-8 items-center justify-center rounded-lg bg-gradient-primary text-white">
              <BookOpenCheck className="size-4" />
            </span>
            <span className="font-semibold">点凡阅卷 · 我的错题练习卷</span>
            <span className="ml-auto text-muted-foreground text-xs">
              生成于 {generatedAt}
            </span>
          </div>
          <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 py-5">
            <h3 className="font-bold text-xl">
              {studentName}
              {className && (
                <span className="ml-2 font-normal text-muted-foreground text-sm">
                  {className}
                </span>
              )}
            </h3>
            <span className="text-muted-foreground text-sm">{scopeText}</span>
            <span className="ml-auto text-muted-foreground text-sm">
              共 {selected.length} 题
            </span>
          </div>
          <p className="pb-5 text-muted-foreground text-xs leading-5">
            把每道题重新做一遍，写完整过程；做完再翻到最后对照参考答案。
          </p>

          {/* 逐题 */}
          {!detailsReady ? (
            <div className="flex flex-col gap-6 border-t pt-6">
              {selected.map((entry) => (
                <Skeleton
                  key={entry.entry_id}
                  className="h-64 w-full rounded-lg"
                />
              ))}
            </div>
          ) : (
            <ol className="flex flex-col gap-8 border-t pt-6">
              {detailQueries.map((query, index) => {
                const detail = query.data
                if (!detail) return null
                return (
                  <li
                    key={detail.entry_id}
                    className="flex flex-col gap-3 break-inside-avoid"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold">第 {index + 1} 题</span>
                      <span className="text-muted-foreground text-xs">
                        {detail.exam_title} · {detail.question_label}
                      </span>
                      {(detail.knowledge_point_names ?? []).map((name) => (
                        <Tag key={name} variant="neutral">
                          {name}
                        </Tag>
                      ))}
                    </div>
                    {detail.question_text && (
                      <p className="whitespace-pre-wrap text-sm leading-7">
                        {detail.question_text}
                      </p>
                    )}
                    {detail.has_image && (
                      <section>
                        <h5 className="mb-2 font-medium text-muted-foreground text-xs print:hidden">
                          我当时的作答
                        </h5>
                        <SheetImage
                          entryId={detail.entry_id}
                          label={detail.question_label}
                        />
                      </section>
                    )}
                    <div className="min-h-48 rounded-lg border border-dashed p-3">
                      <span className="text-muted-foreground text-xs">
                        作答区
                      </span>
                    </div>
                  </li>
                )
              })}
            </ol>
          )}

          {/* 参考答案附页：单独起一页 */}
          {detailsReady && (
            <section className="break-before-page">
              <h4 className="border-b pb-4 font-semibold">参考答案</h4>
              <ol className="flex flex-col gap-5 pt-5">
                {detailQueries.map((query, index) => {
                  const detail = query.data
                  if (!detail) return null
                  return (
                    <li
                      key={detail.entry_id}
                      className="flex flex-col gap-1.5 break-inside-avoid"
                    >
                      <span className="font-medium text-sm">
                        第 {index + 1} 题
                        <span className="ml-2 font-normal text-muted-foreground text-xs">
                          {detail.exam_title} · {detail.question_label}
                        </span>
                      </span>
                      {detail.standard_answer_text && (
                        <p className="whitespace-pre-wrap text-sm leading-6">
                          {detail.standard_answer_text}
                        </p>
                      )}
                      {(detail.scoring_points ?? []).length > 0 && (
                        <ul className="flex flex-col gap-1">
                          {(detail.scoring_points ?? []).map((point, i) => (
                            <li
                              key={`${detail.entry_id}-sp-${i}`}
                              className="text-muted-foreground text-xs leading-5"
                            >
                              · {scoringPointText(point)}
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  )
                })}
              </ol>
              <p className="mt-8 border-t pt-5 text-muted-foreground text-xs">
                本练习卷由点凡阅卷 自动生成 · {generatedAt}
              </p>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
