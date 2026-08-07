import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, Link, redirect } from "@tanstack/react-router"
import { School } from "lucide-react"
import { Suspense } from "react"

import { type UserPublic, UsersService } from "@/client"
import AddUser from "@/components/Admin/AddUser"
import BatchAddTeachers from "@/components/Admin/BatchAddTeachers"
import { columns, type UserTableData } from "@/components/Admin/columns"
import { resolveRole } from "@/components/Admin/roleMeta"
import { DataTable } from "@/components/Common/DataTable"
import PendingUsers from "@/components/Pending/PendingUsers"
import { Button } from "@/components/ui/button"
import useAuth from "@/hooks/useAuth"

function getUsersQueryOptions() {
  return {
    queryFn: () => UsersService.readUsers({ skip: 0, limit: 500 }),
    queryKey: ["users"],
  }
}

/** 平台超管维护平台账号；学校管理者维护本校账号。 */
const ADMIN_ROLES = ["platform_superuser", "school_owner", "school_admin"]

export const Route = createFileRoute("/_layout/admin")({
  component: Admin,
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    if (!ADMIN_ROLES.includes(resolveRole(user))) {
      throw redirect({
        to: "/",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: "用户管理 - 点凡阅卷",
      },
    ],
  }),
})

function UsersTableContent() {
  const { user: currentUser } = useAuth()
  const { data: users } = useSuspenseQuery(getUsersQueryOptions())

  const tableData: UserTableData[] = users.data.map((user: UserPublic) => ({
    ...user,
    isCurrentUser: currentUser?.id === user.id,
  }))

  return <DataTable columns={columns} data={tableData} />
}

function UsersTable() {
  return (
    <Suspense fallback={<PendingUsers />}>
      <UsersTableContent />
    </Suspense>
  )
}

function Admin() {
  const { user: currentUser } = useAuth()
  const currentRole = currentUser ? resolveRole(currentUser) : null
  const canBatchImport =
    currentRole === "school_owner" || currentRole === "school_admin"
  const isPlatformAccountPage = currentRole === "platform_superuser"
  const subtitle = isPlatformAccountPage
    ? "维护点凡平台内部管理员与运营账号"
    : "维护本校账号、角色和任教信息"

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {isPlatformAccountPage ? "平台账号" : "用户管理"}
          </h1>
          <p className="text-muted-foreground">{subtitle}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {isPlatformAccountPage && (
            <Button variant="outline" asChild>
              <Link to="/platform">
                <School />
                学校账号
              </Link>
            </Button>
          )}
          {canBatchImport && <BatchAddTeachers />}
          <AddUser />
        </div>
      </div>
      <UsersTable />
    </div>
  )
}
