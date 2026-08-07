import { EllipsisVertical } from "lucide-react"
import { useState } from "react"

import type { StudentPublic } from "@/client"
import { resolveRole } from "@/components/Admin/roleMeta"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import useAuth from "@/hooks/useAuth"
import BindAccount from "./BindAccount"
import DeleteStudent from "./DeleteStudent"
import EditStudent from "./EditStudent"

interface StudentActionsMenuProps {
  student: StudentPublic
}

export const StudentActionsMenu = ({ student }: StudentActionsMenuProps) => {
  const [open, setOpen] = useState(false)
  const { user } = useAuth()
  const canManageAccounts =
    user && ["school_owner", "school_admin"].includes(resolveRole(user))
  const close = () => setOpen(false)

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon">
          <EllipsisVertical />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <EditStudent student={student} onSuccess={close} />
        {canManageAccounts && (
          <BindAccount student={student} onSuccess={close} />
        )}
        <DeleteStudent student={student} onSuccess={close} />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
