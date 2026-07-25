import { Users } from "lucide-react"

import type { ClassGroupPublic } from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import { Tag } from "@/components/Common/Tag"
import { cn } from "@/lib/utils"
import { ClassActionsMenu } from "./ClassActionsMenu"

interface ClassListProps {
  classes: ClassGroupPublic[]
  selectedId: string | null
  onSelect: (classId: string) => void
  onDeleted: (classId: string) => void
}

/** 左侧班级列表卡：名称/年级/人数，点击选中，行内含改名/删除操作。 */
const ClassList = ({
  classes,
  selectedId,
  onSelect,
  onDeleted,
}: ClassListProps) => {
  return (
    <section className="rounded-2xl border bg-card p-4 shadow-card">
      <h3 className="mb-3 font-semibold text-sm">班级列表</h3>
      {classes.length === 0 ? (
        <EmptyState
          icon={Users}
          title="还没有班级"
          description="点击右上角「新建班级」创建第一个班级。"
        />
      ) : (
        <ul className="flex flex-col gap-1">
          {classes.map((classGroup) => {
            const selected = classGroup.id === selectedId
            return (
              <li key={classGroup.id}>
                <div
                  className={cn(
                    "flex items-center gap-2 rounded-xl px-3 py-2.5 transition-colors",
                    selected
                      ? "bg-primary/10 ring-1 ring-primary/30"
                      : "hover:bg-muted/60",
                  )}
                >
                  <button
                    type="button"
                    className="flex min-w-0 flex-1 flex-col items-start gap-1 text-left"
                    onClick={() => onSelect(classGroup.id)}
                    data-testid={`class-item-${classGroup.id}`}
                  >
                    <span className="flex w-full items-center gap-2">
                      <span className="truncate font-medium text-sm">
                        {classGroup.name}
                      </span>
                      {classGroup.grade_level && (
                        <Tag variant="sky">{classGroup.grade_level}</Tag>
                      )}
                    </span>
                    <span className="text-muted-foreground text-xs">
                      {classGroup.student_count ?? 0} 人
                    </span>
                  </button>
                  <ClassActionsMenu
                    classGroup={classGroup}
                    onDeleted={() => onDeleted(classGroup.id)}
                  />
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

export default ClassList
