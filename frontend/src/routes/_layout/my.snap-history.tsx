import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { Camera, ChevronLeft, History } from "lucide-react"
import { useState } from "react"
import { PageHead } from "@/components/Common/PageHead"
import {
  type SnapRecordListItem,
  type SnapRecordPayload,
  SnapRecordView,
} from "@/components/Common/SnapRecordView"
import { Button } from "@/components/ui/button"
import { workflowApi } from "@/lib/workflow-api"

export const Route = createFileRoute("/_layout/my/snap-history")({
  component: MySnapHistoryPage,
  head: () => ({ meta: [{ title: "拍题记录 - 点凡阅卷" }] }),
})

/** 拍题记录：拍题答疑/拍照批改的历史回看。 */
function MySnapHistoryPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const records = useQuery({
    queryKey: ["snap-records"],
    queryFn: () =>
      workflowApi<SnapRecordListItem[]>("/students/me/snap/records?limit=50"),
  })
  const detail = useQuery({
    queryKey: ["snap-record", selectedId],
    queryFn: () =>
      workflowApi<{ payload: SnapRecordPayload }>(
        `/students/me/snap/records/${selectedId}`,
      ),
    enabled: Boolean(selectedId),
  })

  if (selectedId) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-4">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setSelectedId(null)}>
            <ChevronLeft />
            返回列表
          </Button>
        </div>
        {detail.isPending && (
          <p className="text-muted-foreground text-sm">加载中…</p>
        )}
        {detail.isError && (
          <p className="text-destructive text-sm">加载失败，请返回重试</p>
        )}
        {detail.data && <SnapRecordView payload={detail.data.payload} />}
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <PageHead
        title="拍题记录"
        subtitle="拍题答疑和拍照批改的历史都在这里，点开就能回看"
      />
      {records.isPending && (
        <p className="text-muted-foreground text-sm">加载中…</p>
      )}
      {records.data?.length === 0 && (
        <div className="grid gap-3 rounded-[10px] border bg-card p-8 text-center">
          <History className="mx-auto size-8 text-muted-foreground" />
          <p className="text-muted-foreground text-sm">
            还没有拍过题。去拍一道，结果会自动存在这里。
          </p>
          <div>
            <Button asChild>
              <Link to="/my/snap">
                <Camera />
                去拍题
              </Link>
            </Button>
          </div>
        </div>
      )}
      <div className="grid gap-2">
        {records.data?.map((item) => (
          <button
            key={item.id}
            type="button"
            data-testid="snap-record-item"
            className="rounded-[10px] border bg-card px-4 py-3 text-left transition-colors hover:border-primary"
            onClick={() => setSelectedId(item.id)}
          >
            <div className="truncate text-sm">{item.title}</div>
            <div className="mt-1 text-muted-foreground text-xs">
              {item.mode === "grade" ? "拍照批改" : "拍题答疑"} ·{" "}
              {new Date(item.created_at).toLocaleString("zh-CN", {
                month: "numeric",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
