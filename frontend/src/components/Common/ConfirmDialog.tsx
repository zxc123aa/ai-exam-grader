import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"

/**
 * shadcn 风格的确认对话框，用于替代 window.confirm。
 * 受控组件：父组件维护 open 状态，确认/取消都会通过 onOpenChange(false) 关闭。
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmText = "确认",
  cancelText = "取消",
  loading = false,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description?: ReactNode
  confirmText?: string
  cancelText?: string
  loading?: boolean
  onConfirm: () => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={loading}
            onClick={() => onOpenChange(false)}
          >
            {cancelText}
          </Button>
          <LoadingButton
            type="button"
            variant="destructive"
            loading={loading}
            onClick={onConfirm}
          >
            {confirmText}
          </LoadingButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
