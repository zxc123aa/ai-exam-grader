import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link2, Link2Off } from "lucide-react"
import { useState } from "react"

import {
  ClassesService,
  type StudentPublic,
  type UserPublic,
  UsersService,
} from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { DropdownMenuItem } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

interface BindAccountProps {
  student: StudentPublic
  onSuccess: () => void
}

/**
 * 绑定/解绑登录账号。
 * 账号候选列表来自 GET /users/（仅 admin+ 可用）：拉取失败（如教师 403）时
 * 降级为手动输入用户 ID，保证教师也能完成绑定。
 */
const BindAccount = ({ student, onSuccess }: BindAccountProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const [selectedUserId, setSelectedUserId] = useState("")
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()

  const usersQuery = useQuery({
    queryKey: ["student-account-candidates"],
    queryFn: () => UsersService.readUsers({ skip: 0, limit: 100 }),
    retry: false,
    enabled: isOpen && !student.user_id,
  })

  const studentUsers: UserPublic[] = (usersQuery.data?.data ?? []).filter(
    (user) => user.role === "student",
  )
  // 用户列表不可用（无权限）时降级为手动输入用户 ID
  const fallbackToInput = usersQuery.isError

  const bindMutation = useMutation({
    mutationFn: (userId: string) =>
      ClassesService.bindStudentAccount({
        studentId: student.id,
        requestBody: { user_id: userId },
      }),
    onSuccess: () => {
      showSuccessToast("账号绑定成功")
      setIsOpen(false)
      onSuccess()
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["classes"] })
    },
  })

  const unbindMutation = useMutation({
    mutationFn: () =>
      ClassesService.unbindStudentAccount({ studentId: student.id }),
    onSuccess: () => {
      showSuccessToast("已解绑账号")
      setIsOpen(false)
      onSuccess()
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["classes"] })
    },
  })

  const onBind = () => {
    if (!selectedUserId.trim()) {
      showErrorToast("请选择或输入要绑定的用户")
      return
    }
    bindMutation.mutate(selectedUserId.trim())
  }

  const isPending = bindMutation.isPending || unbindMutation.isPending

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DropdownMenuItem
        onSelect={(e) => e.preventDefault()}
        onClick={() => setIsOpen(true)}
      >
        {student.user_id ? <Link2Off /> : <Link2 />}
        {student.user_id ? "解绑账号" : "绑定账号"}
      </DropdownMenuItem>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{student.user_id ? "解绑账号" : "绑定账号"}</DialogTitle>
          <DialogDescription>
            {student.user_id
              ? `学生「${student.name}」已绑定登录账号，解绑后该账号将不再关联此学生。`
              : `为学生「${student.name}」绑定一个学生角色的登录账号。`}
          </DialogDescription>
        </DialogHeader>

        {student.user_id ? (
          <div className="py-4 text-muted-foreground text-sm">
            当前绑定用户 ID：
            <span className="font-mono">{student.user_id}</span>
          </div>
        ) : (
          <div className="grid gap-2 py-4">
            {fallbackToInput ? (
              <>
                <Input
                  placeholder="请输入学生账号的用户 ID"
                  value={selectedUserId}
                  onChange={(e) => setSelectedUserId(e.target.value)}
                  data-testid="bind-user-id-input"
                />
                <p className="text-muted-foreground text-xs">
                  当前账号无用户列表权限，请手动输入学生账号的用户
                  ID（可由管理员在用户管理中查看）。
                </p>
              </>
            ) : (
              <Select
                value={selectedUserId}
                onValueChange={setSelectedUserId}
                disabled={usersQuery.isLoading}
              >
                <SelectTrigger data-testid="bind-user-select">
                  <SelectValue
                    placeholder={
                      usersQuery.isLoading ? "加载账号列表…" : "请选择学生账号"
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {studentUsers.map((user) => (
                    <SelectItem key={user.id} value={user.id}>
                      {user.full_name ? `${user.full_name}（` : ""}
                      {user.email}
                      {user.full_name ? "）" : ""}
                    </SelectItem>
                  ))}
                  {studentUsers.length === 0 && !usersQuery.isLoading && (
                    <SelectItem value="__empty" disabled>
                      暂无学生角色的账号
                    </SelectItem>
                  )}
                </SelectContent>
              </Select>
            )}
          </div>
        )}

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" disabled={isPending}>
              取消
            </Button>
          </DialogClose>
          {student.user_id ? (
            <LoadingButton
              variant="destructive"
              loading={isPending}
              onClick={() => unbindMutation.mutate()}
            >
              确认解绑
            </LoadingButton>
          ) : (
            <LoadingButton loading={isPending} onClick={onBind}>
              绑定
            </LoadingButton>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default BindAccount
