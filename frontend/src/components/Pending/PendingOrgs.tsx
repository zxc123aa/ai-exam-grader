import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const HEADERS = [
  "学校名称",
  "代码",
  "状态",
  "考试数",
  "学生数",
  "老师数",
  "创建时间",
]

const PendingOrgs = () => (
  <Table>
    <TableHeader>
      <TableRow>
        {HEADERS.map((header) => (
          <TableHead key={header}>{header}</TableHead>
        ))}
        <TableHead>
          <span className="sr-only">操作</span>
        </TableHead>
      </TableRow>
    </TableHeader>
    <TableBody>
      {Array.from({ length: 4 }).map((_, index) => (
        <TableRow key={index}>
          <TableCell>
            <Skeleton className="h-4 w-32" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-4 w-16" />
          </TableCell>
          <TableCell>
            <Skeleton className="h-5 w-14 rounded-full" />
          </TableCell>
          {Array.from({ length: 3 }).map((_, i) => (
            <TableCell key={i}>
              <Skeleton className="h-4 w-8" />
            </TableCell>
          ))}
          <TableCell>
            <Skeleton className="h-4 w-20" />
          </TableCell>
          <TableCell>
            <div className="flex justify-end">
              <Skeleton className="h-8 w-20 rounded-md" />
            </div>
          </TableCell>
        </TableRow>
      ))}
    </TableBody>
  </Table>
)

export default PendingOrgs
