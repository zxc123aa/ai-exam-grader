import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { BookMarked, FileText, Network } from "lucide-react"
import {
  ApiError,
  type KnowledgeTrendScorePoint,
  type KnowledgeTrendsPublic,
  StudentsService,
  type WrongbookMasteryItem,
} from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHead } from "@/components/Common/PageHead"
import { ProgressBar, type ProgressTone } from "@/components/Common/ProgressBar"
import { Tag } from "@/components/Common/Tag"
import { DonutChart, type DonutSegment } from "@/components/charts/DonutChart"
import { LineChart, type LineSeries } from "@/components/charts/LineChart"
import { CHART_PALETTE } from "@/components/charts/theme"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"

export const Route = createFileRoute("/_layout/my/knowledge")({
  component: MyKnowledgePage,
  head: () => ({ meta: [{ title: "知识图谱 - 点凡阅卷" }] }),
})

/** 掌握度 = 100 - 错误率：错得越少掌握越好。 */
function masteryOf(row: WrongbookMasteryItem): number {
  return Math.min(100, Math.max(0, 100 - (row.wrong_rate ?? 0)))
}

/** 每个知识点只做过 1-2 题时，错误率换算的掌握度没有统计意义，不显示百分比。 */
const MIN_SAMPLE = 3

function hasEnoughSamples(row: WrongbookMasteryItem): boolean {
  return (row.attempts ?? 0) >= MIN_SAMPLE
}

type MasteryLevel = "solid" | "normal" | "weak"

function levelOf(mastery: number): MasteryLevel {
  if (mastery >= 80) return "solid"
  if (mastery >= 50) return "normal"
  return "weak"
}

const LEVEL_META: Record<
  MasteryLevel,
  { label: string; tone: ProgressTone; color: string }
> = {
  solid: { label: "牢固", tone: "mint", color: "var(--chart-5)" },
  normal: { label: "一般", tone: "amber", color: "var(--chart-3)" },
  weak: { label: "薄弱", tone: "red", color: "var(--destructive)" },
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

/** 场次横轴标签：优先考试日期（M/D），同名同日的重复发布补上发布时间区分。 */
function trendLabels(releases: KnowledgeTrendScorePoint[]): string[] {
  const base = releases.map((point) => {
    if (point.exam_date) {
      const date = new Date(point.exam_date)
      if (!Number.isNaN(date.getTime()))
        return `${date.getMonth() + 1}/${date.getDate()}`
    }
    return point.exam_title
  })
  if (new Set(base).size === base.length) return base
  return releases.map((point, index) => {
    const time = new Date(point.released_at)
    const suffix = Number.isNaN(time.getTime())
      ? `#${index + 1}`
      : `${String(time.getHours()).padStart(2, "0")}:${String(time.getMinutes()).padStart(2, "0")}`
    return `${base[index]} ${suffix}`
  })
}

function scoreRateOf(point: KnowledgeTrendScorePoint): number | null {
  if (point.total_score == null || !point.total_max_score) return null
  return Math.round((point.total_score / point.total_max_score) * 100)
}

/** 长期趋势：总分得分率曲线 + 错误数前 5 知识点的错误率曲线。 */
function TrendSection({ trends }: { trends: KnowledgeTrendsPublic }) {
  const releases = trends.score_trend ?? []
  if (releases.length === 0) return null
  const labels = trendLabels(releases)

  if (releases.length === 1) {
    const only = releases[0]
    const rate = scoreRateOf(only)
    return (
      <section className="flex flex-col gap-3">
        <h3 className="font-semibold">长期趋势</h3>
        <div className="rounded-2xl bg-card p-5 shadow-card">
          <div className="flex items-center gap-2">
            <span className="font-medium">{only.exam_title}</span>
            {only.exam_date && (
              <span className="text-muted-foreground text-xs">
                {formatDate(only.exam_date)}
              </span>
            )}
            <span className="ml-auto font-semibold tabular-nums">
              得分率 {rate ?? 0}%
            </span>
          </div>
          <ProgressBar value={rate ?? 0} slim className="mt-2" />
          <p className="mt-2 text-muted-foreground text-xs">
            再考一场就能看到趋势
          </p>
        </div>
      </section>
    )
  }

  const scoreSeries: LineSeries[] = [
    { name: "得分率", data: releases.map(scoreRateOf) },
  ]
  // 后端已按总错误数降序排，取前 5；知识点没出现的场次留空（断线）
  const kpSeries: LineSeries[] = (trends.kp_trends ?? [])
    .slice(0, 5)
    .map((series) => {
      const byRelease = new Map(
        (series.points ?? []).map((point) => [
          point.released_at,
          point.wrong_rate ?? 0,
        ]),
      )
      return {
        name: series.knowledge_point,
        data: releases.map((point) => byRelease.get(point.released_at) ?? null),
      }
    })

  return (
    <section className="flex flex-col gap-3">
      <h3 className="font-semibold">长期趋势</h3>
      <div className="rounded-2xl bg-card p-5 shadow-card">
        <p className="mb-2 font-medium text-muted-foreground text-xs">
          总分得分率
        </p>
        <LineChart
          labels={labels}
          series={scoreSeries}
          unit="%"
          yMin={0}
          yMax={100}
        />
      </div>
      {kpSeries.length > 0 && (
        <div className="rounded-2xl bg-card p-5 shadow-card">
          <p className="mb-2 font-medium text-muted-foreground text-xs">
            知识点错误率（错得最多的 {kpSeries.length} 个）
          </p>
          <LineChart
            labels={labels}
            series={kpSeries}
            unit="%"
            yMin={0}
            yMax={100}
          />
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {kpSeries.map((series, index) => (
              <span
                key={series.name}
                className="flex items-center gap-1.5 text-muted-foreground text-xs"
              >
                <span
                  className="inline-block size-2 rounded-full"
                  style={{
                    backgroundColor:
                      CHART_PALETTE[index % CHART_PALETTE.length],
                  }}
                />
                {series.name}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

/** 总览：掌握度分布环图 + 平均掌握度大数字。样本不足的知识点不参与统计。 */
function OverviewSection({ rows }: { rows: WrongbookMasteryItem[] }) {
  const reliable = rows.filter(hasEnoughSamples)
  const counts: Record<MasteryLevel, number> = { solid: 0, normal: 0, weak: 0 }
  for (const row of reliable) counts[levelOf(masteryOf(row))] += 1
  const average = reliable.length
    ? Math.round(
        reliable.reduce((sum, row) => sum + masteryOf(row), 0) /
          reliable.length,
      )
    : null
  const segments: DonutSegment[] = (
    ["solid", "normal", "weak"] as MasteryLevel[]
  ).map((level) => ({
    name: LEVEL_META[level].label,
    value: counts[level],
    color: LEVEL_META[level].color,
  }))

  return (
    <div className="flex flex-wrap items-center gap-8 rounded-2xl bg-card p-6 shadow-card">
      <DonutChart segments={segments} size={150} stroke={16} />
      <div>
        <p className="text-muted-foreground text-sm">平均掌握度</p>
        {average === null ? (
          <p className="mt-1 font-bold text-2xl tracking-tight">数据积累中</p>
        ) : (
          <p className="mt-1 font-bold text-4xl tabular-nums tracking-tight">
            {average}
            <span className="ml-0.5 font-medium text-muted-foreground text-xl">
              %
            </span>
          </p>
        )}
        <p className="mt-2 text-muted-foreground text-sm">
          共 {rows.length} 个知识点
          {counts.weak > 0 && (
            <>
              {"，"}
              <span className="text-red-600 dark:text-red-400">
                {counts.weak} 个薄弱
              </span>
            </>
          )}
          {rows.length - reliable.length > 0 && (
            <>
              {"，"}
              {rows.length - reliable.length} 个样本不足
            </>
          )}
        </p>
        <p className="mt-1 text-muted-foreground text-xs">
          每个知识点至少做 {MIN_SAMPLE} 题才纳入掌握度统计
        </p>
      </div>
    </div>
  )
}

/** 知识点矩阵：按科目分组，一行一个知识点，点行进错题本看对应错题。 */
function MatrixSection({ rows }: { rows: WrongbookMasteryItem[] }) {
  const groups = new Map<string, WrongbookMasteryItem[]>()
  for (const row of rows) {
    const subject = row.subject ?? "未分科"
    const list = groups.get(subject) ?? []
    list.push(row)
    groups.set(subject, list)
  }

  return (
    <section className="flex flex-col gap-3">
      <h3 className="font-semibold">知识点矩阵</h3>
      {[...groups.entries()].map(([subject, items]) => (
        <div key={subject} className="rounded-2xl bg-card p-5 shadow-card">
          <p className="mb-3 font-medium text-muted-foreground text-xs">
            {subject}
          </p>
          <ul className="flex flex-col divide-y">
            {items.map((row) => {
              const mastery = masteryOf(row)
              const enough = hasEnoughSamples(row)
              const meta = LEVEL_META[levelOf(mastery)]
              const lastWrong = formatDate(row.last_wrong_at)
              return (
                <li key={`${subject}-${row.knowledge_point_name}`}>
                  <Link
                    to="/my/wrongbook"
                    search={{ kp: row.knowledge_point_name }}
                    className="-mx-2 flex flex-col gap-1.5 rounded-lg px-2 py-3 transition-colors hover:bg-muted/50"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-medium">
                        {row.knowledge_point_name}
                      </span>
                      <Tag variant="neutral">
                        {enough ? meta.label : "样本不足"}
                      </Tag>
                      {enough && (
                        <span className="ml-auto font-semibold tabular-nums">
                          {mastery}%
                        </span>
                      )}
                    </div>
                    {enough && (
                      <ProgressBar
                        value={mastery}
                        tone={meta.tone}
                        slim
                        className="max-w-md"
                      />
                    )}
                    <p className="text-muted-foreground text-xs">
                      答题 {row.attempts ?? 0} · 错 {row.wrong_count ?? 0}
                      {lastWrong ? ` · 最近出错 ${lastWrong}` : ""}
                    </p>
                  </Link>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </section>
  )
}

/** 最该补的 3 块：掌握度最低的知识点，一键生成对应错题卷。样本不足的不参评。 */
function WeakSpotSection({ rows }: { rows: WrongbookMasteryItem[] }) {
  const weakest = [...rows]
    .filter(hasEnoughSamples)
    .sort((a, b) => masteryOf(a) - masteryOf(b))
    .slice(0, 3)

  if (weakest.length === 0) return null

  return (
    <section className="flex flex-col gap-3">
      <h3 className="font-semibold">最该补的 3 块</h3>
      <div className="flex flex-col gap-3 sm:flex-row">
        {weakest.map((row, order) => {
          const mastery = masteryOf(row)
          return (
            <div
              key={`${row.subject ?? ""}-${row.knowledge_point_name}`}
              className="flex-1 rounded-2xl bg-card p-4 shadow-card"
            >
              <div className="flex items-center gap-2">
                <span className="font-medium text-muted-foreground text-xs">
                  {order + 1}
                </span>
                <span className="font-medium">{row.knowledge_point_name}</span>
                {row.subject && (
                  <span className="text-muted-foreground text-xs">
                    {row.subject}
                  </span>
                )}
                <span className="ml-auto font-semibold text-red-600 tabular-nums dark:text-red-400">
                  {mastery}%
                </span>
              </div>
              <ProgressBar
                value={mastery}
                tone={LEVEL_META[levelOf(mastery)].tone}
                slim
                className="mt-2"
              />
              <Button asChild variant="outline" size="sm" className="mt-3">
                <Link
                  to="/my/wrongbook-sheet"
                  search={{
                    kps: row.knowledge_point_name,
                    range: "90d",
                    limit: 10,
                  }}
                >
                  <FileText className="size-4" />
                  生成错题卷
                </Link>
              </Button>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function MyKnowledgePage() {
  const query = useQuery({
    queryKey: ["my-wrongbook-mastery"],
    queryFn: () => StudentsService.readMyMastery(),
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 3,
  })
  const trendsQuery = useQuery({
    queryKey: ["my-knowledge-trends"],
    queryFn: () => StudentsService.readMyKnowledgeTrends(),
  })

  const rows = query.data?.data ?? []

  return (
    <div className="flex flex-col gap-6">
      <PageHead
        title="知识图谱"
        subtitle="按知识点看你的掌握情况"
        actions={
          <Button asChild variant="ghost">
            <Link to="/my/wrongbook" search={{ kp: undefined }}>
              <BookMarked className="size-4" />
              我的错题本
            </Link>
          </Button>
        }
      />

      {query.isPending ? (
        <div className="flex flex-col gap-4">
          {["s1", "s2", "s3"].map((key) => (
            <Skeleton key={key} className="h-32 rounded-2xl" />
          ))}
        </div>
      ) : query.isError ? (
        <p className="text-destructive text-sm">
          知识图谱加载失败：{String(query.error)}
        </p>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Network}
          title="还没有掌握度数据"
          description="考完一场试再来看看"
        />
      ) : (
        <>
          <OverviewSection rows={rows} />
          {trendsQuery.data && <TrendSection trends={trendsQuery.data} />}
          <WeakSpotSection rows={rows} />
          <MatrixSection rows={rows} />
        </>
      )}
    </div>
  )
}
