import { EllipsisVertical } from "lucide-react"
import { useState } from "react"

import type { ClassGroupPublic } from "@/client"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import DeleteClass from "./DeleteClass"
import RenameClass from "./RenameClass"

interface ClassActionsMenuProps {
  classGroup: ClassGroupPublic
  onDeleted?: () => void
}

export const ClassActionsMenu = ({
  classGroup,
  onDeleted,
}: ClassActionsMenuProps) => {
  const [open, setOpen] = useState(false)

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon">
          <EllipsisVertical />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <RenameClass classGroup={classGroup} onSuccess={() => setOpen(false)} />
        <DeleteClass
          classGroup={classGroup}
          onSuccess={() => {
            setOpen(false)
            onDeleted?.()
          }}
        />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
