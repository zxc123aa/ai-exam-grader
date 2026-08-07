import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Search,
  Users,
} from "lucide-react"
import { useDeferredValue, useState } from "react"

import { type PlatformDirectoryItem, PlatformService } from "@/client"
import { ROLE_LABELS, ROLE_TAG_VARIANTS } from "@/components/Admin/roleMeta"
import { EmptyState } from "@/components/Common/EmptyState"
import { Tag } from "@/components/Common/Tag"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { AddOrgOwner } from "./AddOrgOwner"

const PAGE_SIZE = 20

type DirectoryCategory = "all" | "admins" | "teachers" | "students" | "unlinked"

const CATEGORIES: Array<{ value: DirectoryCategory; label: string }> = [
  { value: "all", label: "全部" },
  { value: "admins", label: "管理员" },
  { value: "teachers", label: "老师" },
  { value: "students", label: "学生" },
  { value: "unlinked", label: "需关联" },
]

const LINK_STATUS: Record<
  string,
  { label: string; variant: "mint" | "amber" | "neutral" }
> = {
  bound: { label: "已绑定账号", variant: "mint" },
  no_account: { label: "未开通账号", variant: "amber" },
  no_roster: { label: "未关联名册", variant: "amber" },
  not_applicable: { label: "登录账号", variant: "neutral" },
}

function PersonScope({
  item,
  showSchool,
}: {
  item: PlatformDirectoryItem
  showSchool: boolean
}) {
  const classLabel = item.class_names?.length
    ? item.class_names.join("、")
    : item.class_name
  return (
    <span className="text-muted-foreground text-xs">
      {[showSchool ? item.org_name : null, classLabel]
        .filter(Boolean)
        .join(" · ") || "全校"}
    </span>
  )
}

function PersonIdentity({
  item,
  showSchool,
}: {
  item: PlatformDirectoryItem
  showSchool: boolean
}) {
  return (
    <div className="min-w-0">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="font-medium">{item.name}</span>
        <Tag variant={ROLE_TAG_VARIANTS[item.role]}>
          {ROLE_LABELS[item.role]}
        </Tag>
      </div>
      <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
        <PersonScope item={item} showSchool={showSchool} />
        <span className="font-mono text-[11px] text-muted-foreground/70">
          {item.record_id.slice(0, 8)}
        </span>
      </div>
    </div>
  )
}

function AccountState({ item }: { item: PlatformDirectoryItem }) {
  const status = LINK_STATUS[item.link_status] ?? LINK_STATUS.not_applicable
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Tag variant={status.variant}>{status.label}</Tag>
      {item.is_active === false && <Tag variant="red">已停用</Tag>}
    </div>
  )
}

function DirectoryRows({
  rows,
  showSchool,
}: {
  rows: PlatformDirectoryItem[]
  showSchool: boolean
}) {
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40 hover:bg-muted/40">
              <TableHead>姓名</TableHead>
              <TableHead>联系方式 / 编号</TableHead>
              <TableHead>账号状态</TableHead>
              {showSchool && <TableHead className="w-24" />}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((item) => (
              <TableRow key={`${item.record_type}-${item.record_id}`}>
                <TableCell>
                  <PersonIdentity item={item} showSchool={showSchool} />
                </TableCell>
                <TableCell>
                  <div className="grid gap-0.5 text-sm">
                    <span className="break-all text-muted-foreground">
                      {item.email || "未开通登录邮箱"}
                    </span>
                    {item.person_no && (
                      <span className="text-muted-foreground text-xs">
                        {item.role === "student" ? "学号" : "工号"}：
                        {item.person_no}
                      </span>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  <AccountState item={item} />
                </TableCell>
                {showSchool && (
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      asChild
                      title="查看学校"
                    >
                      <Link
                        to="/platform/$orgId"
                        params={{ orgId: item.org_id }}
                      >
                        <ArrowRight />
                        <span className="sr-only">查看学校</span>
                      </Link>
                    </Button>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="divide-y md:hidden">
        {rows.map((item) => (
          <div
            key={`${item.record_type}-${item.record_id}`}
            className="grid min-w-0 gap-3 px-4 py-4"
          >
            <div className="flex min-w-0 items-start justify-between gap-3">
              <PersonIdentity item={item} showSchool={showSchool} />
              {showSchool && (
                <Button variant="ghost" size="icon-sm" asChild title="查看学校">
                  <Link to="/platform/$orgId" params={{ orgId: item.org_id }}>
                    <ArrowRight />
                    <span className="sr-only">查看学校</span>
                  </Link>
                </Button>
              )}
            </div>
            <div className="min-w-0 text-sm">
              <p className="break-all text-muted-foreground">
                {item.email || "未开通登录邮箱"}
              </p>
              {item.person_no && (
                <p className="mt-0.5 text-muted-foreground text-xs">
                  {item.role === "student" ? "学号" : "工号"}：{item.person_no}
                </p>
              )}
            </div>
            <AccountState item={item} />
          </div>
        ))}
      </div>
    </>
  )
}

function DirectoryPanel({
  orgId,
  query,
  onQueryChange,
  showSchool,
  showCategories,
  canAddOwner = false,
}: {
  orgId?: string
  query: string
  onQueryChange: (value: string) => void
  showSchool: boolean
  showCategories: boolean
  canAddOwner?: boolean
}) {
  const deferredQuery = useDeferredValue(query.trim())
  const [category, setCategory] = useState<DirectoryCategory>("all")
  const [page, setPage] = useState(1)
  const enabled = Boolean(orgId || deferredQuery)

  const directoryQuery = useQuery({
    queryKey: [
      "platform-directory",
      orgId ?? "all-orgs",
      deferredQuery,
      category,
      page,
    ],
    queryFn: () =>
      PlatformService.readPlatformDirectory({
        orgId,
        q: deferredQuery || undefined,
        category,
        offset: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    enabled,
  })
  const result = directoryQuery.data
  const totalPages = Math.max(1, Math.ceil((result?.count ?? 0) / PAGE_SIZE))

  return (
    <section
      className="overflow-hidden rounded-[10px] border bg-card"
      data-testid={
        showSchool ? "platform-directory-search" : "platform-org-directory"
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-4 sm:px-5">
        <div>
          <h2 className="font-semibold">
            {showSchool ? "查找学校人员" : "账号与学生"}
          </h2>
          {!showSchool && (
            <p className="mt-1 text-muted-foreground text-xs">
              管理员、老师、学生名册与登录账号统一核对
            </p>
          )}
        </div>
        {!showSchool && canAddOwner && <AddOrgOwner orgId={orgId as string} />}
      </div>

      <div className="flex flex-col gap-3 border-b px-4 py-3 sm:px-5">
        <div className="relative max-w-2xl">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => {
              setPage(1)
              onQueryChange(event.target.value)
            }}
            placeholder={
              showSchool
                ? "搜索姓名、邮箱、学号、工号、学校或班级"
                : "搜索姓名、邮箱、学号、工号或班级"
            }
            className="pl-9"
            aria-label="搜索人员"
            data-testid="directory-search-input"
          />
        </div>
        {showCategories && (
          <div className="flex max-w-full gap-1 overflow-x-auto pb-0.5">
            {CATEGORIES.map((item) => (
              <Button
                key={item.value}
                type="button"
                size="sm"
                variant={category === item.value ? "default" : "ghost"}
                className="h-7 px-3"
                onClick={() => {
                  setPage(1)
                  setCategory(item.value)
                }}
              >
                {item.label}
              </Button>
            ))}
          </div>
        )}
      </div>

      {!enabled ? null : directoryQuery.isPending ? (
        <Skeleton className="h-56 rounded-none" />
      ) : result && result.data.length > 0 ? (
        <>
          <DirectoryRows rows={result.data} showSchool={showSchool} />
          <div className="flex items-center justify-between gap-3 border-t px-4 py-3 text-sm sm:px-5">
            <span className="text-muted-foreground tabular-nums">
              共 {result.count} 条
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="icon-sm"
                title="上一页"
                disabled={page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                <ChevronLeft />
              </Button>
              <span className="min-w-14 text-center text-muted-foreground tabular-nums">
                {page} / {totalPages}
              </span>
              <Button
                variant="outline"
                size="icon-sm"
                title="下一页"
                disabled={page >= totalPages}
                onClick={() => setPage((current) => current + 1)}
              >
                <ChevronRight />
              </Button>
            </div>
          </div>
        </>
      ) : (
        <EmptyState
          icon={Users}
          title={
            category === "unlinked" ? "没有需要关联的人员" : "没有找到人员"
          }
          className="rounded-none border-0 shadow-none"
        />
      )}
    </section>
  )
}

export function PlatformDirectorySearch({
  query,
  onQueryChange,
}: {
  query: string
  onQueryChange: (value: string) => void
}) {
  return (
    <DirectoryPanel
      query={query}
      onQueryChange={onQueryChange}
      showSchool
      showCategories={false}
    />
  )
}

export function OrgPeopleDirectory({
  orgId,
  canAddOwner,
}: {
  orgId: string
  canAddOwner: boolean
}) {
  const [query, setQuery] = useState("")
  return (
    <DirectoryPanel
      orgId={orgId}
      query={query}
      onQueryChange={setQuery}
      showSchool={false}
      showCategories
      canAddOwner={canAddOwner}
    />
  )
}
