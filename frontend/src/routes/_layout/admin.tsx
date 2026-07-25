import { useSuspenseQuery } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { Suspense } from "react"

import { type UserPublic, UsersService } from "@/client"
import AddUser from "@/components/Admin/AddUser"
import BatchAddTeachers from "@/components/Admin/BatchAddTeachers"
import { columns, type UserTableData } from "@/components/Admin/columns"
import { resolveRole } from "@/components/Admin/roleMeta"
import { DataTable } from "@/components/Common/DataTable"
import PendingUsers from "@/components/Pending/PendingUsers"
import useAuth from "@/hooks/useAuth"

function getUsersQueryOptions() {
  return {
    queryFn: () => UsersService.readUsers({ skip: 0, limit: 500 }),
    queryKey: ["users"],
  }
}

/** 可进入用户管理的角色：平台超管 + 学校管理者（学校角色后端已限定本校数据）。 */
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
  const canBatchImport =
    currentUser && ADMIN_ROLES.includes(resolveRole(currentUser))

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">用户管理</h1>
          <p className="text-muted-foreground">
            Manage user accounts and permissions
          </p>
        </div>
        <div className="flex items-center gap-2">
          {canBatchImport && <BatchAddTeachers />}
          <AddUser />
        </div>
      </div>
      <UsersTable />
    </div>
  )
}
