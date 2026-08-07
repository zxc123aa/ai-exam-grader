import { createFileRoute } from "@tanstack/react-router"

import { CommerceOperations } from "@/components/Platform/CommerceOperations"
import { requirePlatformFinanceRole } from "@/components/Platform/orgMeta"

export const Route = createFileRoute("/_layout/platform_/commerce")({
  component: CommerceOperations,
  beforeLoad: requirePlatformFinanceRole,
  head: () => ({
    meta: [{ title: "订单与财务 - 点凡阅卷" }],
  }),
})
