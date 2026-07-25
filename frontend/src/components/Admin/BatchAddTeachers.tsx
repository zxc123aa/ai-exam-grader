import { useMutation, useQueryClient } from "@tanstack/react-query"
import { ListPlus } from "lucide-react"
import { useRef, useState } from "react"

import {
  type TeacherBatchResult,
  type TeacherBatchRow,
  type TeacherBatchRowResult,
  UsersService,
} from "@/client"
import { Tag } from "@/components/Common/Tag"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { LoadingButton } from "@/components/ui/loading-button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

type Step = "input" | "preview" | "done"

/** 解析教师名单：每行「姓名,邮箱,工号,科目,任教班级」，第 5 列起都视为任教班级。 */
function parseTeacherRows(text: string): TeacherBatchRow[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const fields = line.split(/[,，\t]/).map((f) => f.trim())
      return {
        name: fields[0] || null,
        email: fields[1] || null,
        employee_no: fields[2] || null,
        subjects: fields[3] || null,
        class_names: fields.slice(4).filter(Boolean).join(",") || null,
      }
    })
    .filter((row) => row.name || row.email)
}

function ActionTag({ row }: { row: TeacherBatchRowResult }) {
  if (row.action === "create") {
    return <Tag variant="mint">新建</Tag>
  }
  if (row.action === "skip_exists") {
    return <Tag variant="neutral">已存在跳过</Tag>
  }
  return (
    <span className="text-red-600 text-sm dark:text-red-400">
      {row.message || "错误"}
    </span>
  )
}

/** 批量导入老师：录入（CSV/粘贴）→ dry_run 预览 → 确认落库。 */
const BatchAddTeachers = () => {
  const [isOpen, setIsOpen] = useState(false)
  const [step, setStep] = useState<Step>("input")
  const [text, setText] = useState("")
  const [fileText, setFileText] = useState("")
  const [fileName, setFileName] = useState("")
  const [preview, setPreview] = useState<TeacherBatchResult | null>(null)
  const [result, setResult] = useState<TeacherBatchResult | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()

  const reset = () => {
    setStep("input")
    setText("")
    setFileText("")
    setFileName("")
    setPreview(null)
    setResult(null)
  }

  const sourceText = text.trim() ? text : fileText

  const previewMutation = useMutation({
    mutationFn: (rows: TeacherBatchRow[]) =>
      UsersService.createTeachersBatch({
        requestBody: { rows, dry_run: true },
      }),
    onSuccess: (data) => {
      setPreview(data)
      setStep("preview")
    },
    onError: handleError.bind(showErrorToast),
  })

  const importMutation = useMutation({
    mutationFn: (rows: TeacherBatchRow[]) =>
      UsersService.createTeachersBatch({
        requestBody: { rows, dry_run: false },
      }),
    onSuccess: (data) => {
      setResult(data)
      setStep("done")
    },
    onError: handleError.bind(showErrorToast),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
    },
  })

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setFileName(file.name)
    const reader = new FileReader()
    reader.onload = () => setFileText(String(reader.result ?? ""))
    reader.readAsText(file)
  }

  const onPreview = () => {
    const rows = parseTeacherRows(sourceText)
    if (rows.length === 0) {
      showErrorToast(
        "请先粘贴名单或选择 CSV 文件，每行：姓名,邮箱,工号,科目,任教班级",
      )
      return
    }
    previewMutation.mutate(rows)
  }

  const onConfirm = () => {
    importMutation.mutate(parseTeacherRows(sourceText))
  }

  const createCount = (preview?.rows ?? []).filter(
    (row) => row.action === "create",
  ).length

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        setIsOpen(open)
        if (!open) reset()
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" className="my-4">
          <ListPlus className="mr-2" />
          批量导入
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>批量导入老师</DialogTitle>
          <DialogDescription>
            {step === "input" && "粘贴名单或选择 CSV 文件，预览确认后再写入。"}
            {step === "preview" && "确认无误后导入，已存在的邮箱会自动跳过。"}
            {step === "done" && "导入完成，新老师初始密码为 Dianfan@2026。"}
          </DialogDescription>
        </DialogHeader>

        {step === "input" && (
          <div className="grid gap-4 py-2">
            <div className="flex items-center gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.txt"
                className="hidden"
                onChange={onFileChange}
              />
              <Button
                variant="outline"
                size="sm"
                onClick={() => fileInputRef.current?.click()}
              >
                选择 CSV 文件
              </Button>
              <span className="truncate text-muted-foreground text-sm">
                {fileName || "未选择文件"}
              </span>
            </div>
            <textarea
              className="min-h-40 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 dark:bg-input/30"
              placeholder={
                "周老师,zhou@test.com,T001,物理,001班\n吴老师,wu@test.com"
              }
              value={text}
              onChange={(e) => setText(e.target.value)}
              data-testid="batch-teacher-names"
            />
            <p className="text-muted-foreground text-xs">
              每行：姓名,邮箱,工号,科目,任教班级（后三项可空；任教多个班级用逗号分隔）。粘贴内容优先于文件。
            </p>
          </div>
        )}

        {step === "preview" && preview && (
          <div className="max-h-80 overflow-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>姓名</TableHead>
                  <TableHead>邮箱</TableHead>
                  <TableHead>结果</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(preview.rows ?? []).map((row, idx) => (
                  <TableRow key={`${row.email}-${idx}`}>
                    <TableCell className="font-medium">{row.name}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {row.email || "—"}
                    </TableCell>
                    <TableCell>
                      <ActionTag row={row} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {step === "done" && result && (
          <div className="grid gap-2 rounded-md border p-4 text-sm">
            <p>
              新建 <span className="font-semibold">{result.created ?? 0}</span>{" "}
              人、跳过{" "}
              <span className="font-semibold">{result.skipped ?? 0}</span> 条
            </p>
            {(result.errors ?? []).length > 0 && (
              <ul className="grid gap-1 text-red-600 dark:text-red-400">
                {(result.errors ?? []).map((err, idx) => (
                  <li key={`${err.email}-${idx}`}>
                    {err.name}
                    {err.email ? `（${err.email}）` : ""}：
                    {err.message || "导入失败"}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <DialogFooter>
          {step === "input" && (
            <>
              <DialogClose asChild>
                <Button variant="outline" disabled={previewMutation.isPending}>
                  取消
                </Button>
              </DialogClose>
              <LoadingButton
                loading={previewMutation.isPending}
                onClick={onPreview}
              >
                预览
              </LoadingButton>
            </>
          )}
          {step === "preview" && (
            <>
              <Button
                variant="outline"
                disabled={importMutation.isPending}
                onClick={() => setStep("input")}
              >
                返回修改
              </Button>
              <LoadingButton
                loading={importMutation.isPending}
                disabled={createCount === 0}
                onClick={onConfirm}
              >
                确认导入 {createCount} 条
              </LoadingButton>
            </>
          )}
          {step === "done" && (
            <DialogClose asChild>
              <Button>完成</Button>
            </DialogClose>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default BatchAddTeachers
