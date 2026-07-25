import { useQuery } from "@tanstack/react-query"

import { UsersService } from "@/client"
import {
  ROLE_LABELS,
  ROLE_TAG_VARIANTS,
  resolveRole,
} from "@/components/Admin/roleMeta"
import { AvatarGradient } from "@/components/Common/AvatarGradient"
import { Tag } from "@/components/Common/Tag"
import { Card } from "@/components/ui/card"
import useAuth from "@/hooks/useAuth"

/** 资料头卡：头像 + 姓名/邮箱 + 身份标签；教师角色附任教信息（学校管理员维护，只读）。 */
const ProfileHeaderCard = () => {
  const { user: currentUser } = useAuth()
  const role = currentUser ? resolveRole(currentUser) : "teacher"
  const showTeaching = role === "teacher" || role === "school_admin"

  // 任教信息（教师/学校管理员）：管理员维护，这里只读展示
  const teaching = useQuery({
    queryKey: ["teaching-profile", currentUser?.id],
    queryFn: () =>
      UsersService.readTeachingProfile({ userId: currentUser?.id as string }),
    enabled: Boolean(currentUser) && showTeaching,
  })

  if (!currentUser) {
    return null
  }

  return (
    <Card className="gap-0 rounded-2xl py-0 shadow-card">
      <div className="flex items-center gap-4 p-5">
        <AvatarGradient
          name={currentUser.full_name || currentUser.email}
          size={56}
        />
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold text-lg">
            {currentUser.full_name || "未填写姓名"}
          </p>
          <p className="truncate text-muted-foreground text-sm">
            {currentUser.email}
          </p>
        </div>
        <Tag variant={ROLE_TAG_VARIANTS[role]} className="shrink-0">
          {ROLE_LABELS[role]}
        </Tag>
      </div>
      {showTeaching && (
        <div className="grid gap-2 border-t p-5">
          {currentUser.employee_no && (
            <div className="flex items-center gap-3 text-sm">
              <span className="w-16 shrink-0 text-muted-foreground">工号</span>
              <span>{currentUser.employee_no}</span>
            </div>
          )}
          <div className="flex items-center gap-3 text-sm">
            <span className="w-16 shrink-0 text-muted-foreground">
              任教班级
            </span>
            {teaching.isPending ? (
              <span className="text-muted-foreground text-xs">加载中…</span>
            ) : teaching.data?.class_names?.length ? (
              <span className="flex flex-wrap gap-1">
                {teaching.data.class_names.map((name) => (
                  <Tag key={name} variant="neutral">
                    {name}
                  </Tag>
                ))}
              </span>
            ) : (
              <span className="text-muted-foreground">未设置</span>
            )}
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="w-16 shrink-0 text-muted-foreground">
              任教科目
            </span>
            <span>
              {teaching.data?.subjects?.length ? (
                teaching.data.subjects.join("、")
              ) : (
                <span className="text-muted-foreground">未设置</span>
              )}
            </span>
          </div>
          <p className="text-muted-foreground text-xs">
            任教信息由学校管理员维护
          </p>
        </div>
      )}
    </Card>
  )
}

export default ProfileHeaderCard
