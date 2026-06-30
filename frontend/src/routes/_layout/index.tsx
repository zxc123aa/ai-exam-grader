import { createFileRoute } from "@tanstack/react-router"

import useAuth from "@/hooks/useAuth"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [
      {
        title: "Dashboard - AI Exam Grader",
      },
    ],
  }),
})

function Dashboard() {
  const { user: currentUser } = useAuth()

  return (
    <div>
      <div>
        <h1 className="text-2xl truncate max-w-sm">AI Exam Grader</h1>
        <p className="text-muted-foreground">
          Signed in as {currentUser?.full_name || currentUser?.email}
        </p>
      </div>
    </div>
  )
}
