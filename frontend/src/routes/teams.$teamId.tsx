import { createFileRoute } from "@tanstack/react-router"

import { requireSignedIn } from "@/features/identity/auth"
import { TeamPage } from "@/features/registration/TeamPage"

export const Route = createFileRoute("/teams/$teamId")({
  beforeLoad: requireSignedIn,
  head: () => ({ meta: [{ title: "隊伍 · FLOW" }] }),
  component: TeamRoute,
})

function TeamRoute() {
  const { teamId } = Route.useParams()
  return <TeamPage key={teamId} teamId={teamId} />
}
