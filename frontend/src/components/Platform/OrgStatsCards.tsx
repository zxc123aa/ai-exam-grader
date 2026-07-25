import { FileText, GraduationCap, Users } from "lucide-react"

import type { PlatformOrgDetail } from "@/client"
import { StatCard } from "@/components/Common/StatCard"

/** 学校详情的统计卡行：考试 / 学生 / 老师数。 */
export function OrgStatsCards({ org }: { org: PlatformOrgDetail }) {
  return (
    <div className="grid gap-4 sm:grid-cols-3" data-testid="org-stats-cards">
      <StatCard
        icon={FileText}
        tone="indigo"
        value={org.exam_count ?? 0}
        unit="场"
        label="考试数"
      />
      <StatCard
        icon={GraduationCap}
        tone="mint"
        value={org.student_count ?? 0}
        unit="人"
        label="学生数"
      />
      <StatCard
        icon={Users}
        tone="sky"
        value={org.teacher_count ?? 0}
        unit="人"
        label="老师数"
      />
    </div>
  )
}
