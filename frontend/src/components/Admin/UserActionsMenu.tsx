import { EllipsisVertical } from "lucide-react"
import { useState } from "react"

import type { UserPublic } from "@/client"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import useAuth from "@/hooks/useAuth"
import DeleteUser from "./DeleteUser"
import EditUser from "./EditUser"
import { resolveRole } from "./roleMeta"

interface UserActionsMenuProps {
  user: UserPublic
}

export const UserActionsMenu = ({ user }: UserActionsMenuProps) => {
  const [open, setOpen] = useState(false)
  const { user: currentUser } = useAuth()

  const currentRole = currentUser ? resolveRole(currentUser) : null
  const targetRole = resolveRole(user)
  const sameSchool = Boolean(
    currentUser?.org_id && currentUser.org_id === user.org_id,
  )
  const canManage =
    currentRole === "platform_superuser"
      ? !user.org_id
      : currentRole === "school_owner"
        ? sameSchool && !targetRole.startsWith("platform_")
        : currentRole === "school_admin"
          ? sameSchool && ["teacher", "student"].includes(targetRole)
          : false

  if (user.id === currentUser?.id || !canManage) {
    return null
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon">
          <EllipsisVertical />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <EditUser user={user} onSuccess={() => setOpen(false)} />
        <DeleteUser id={user.id} onSuccess={() => setOpen(false)} />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
