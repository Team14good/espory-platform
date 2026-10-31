import { useQuery } from "@tanstack/react-query"

import { RouteErrorPage } from "@/components/layout/ErrorPage"
import { Skeleton } from "@/components/ui/skeleton"
import { InviteLinkField } from "./InviteLinkField"
import { teamInviteUrl, teamQueryOptions } from "./queries"
import { RosterList } from "./RosterList"
import { RegistrationStatusBadge } from "./registration-status"

export const TEAM_FULL_REASON = "隊伍已滿"

/** S17 隊伍頁：隊名與報名狀態、邀請連結（Invite link field）、名單（Roster list）。 */
export function TeamPage({ teamId }: { teamId: string }) {
  const team = useQuery(teamQueryOptions(teamId))

  if (team.isPending) {
    return (
      <section
        role="status"
        aria-busy="true"
        className="mx-auto flex w-full max-w-2xl flex-col gap-6 py-8 sm:py-12"
      >
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-32 w-full" />
        <span className="sr-only">載入中</span>
      </section>
    )
  }
  if (team.isError) return <RouteErrorPage error={team.error} />

  const data = team.data
  return (
    <section className="mx-auto flex w-full max-w-2xl flex-col gap-8 py-8 sm:py-12">
      <header className="flex flex-col gap-2">
        <p className="text-caption text-muted-foreground">
          {data.tournament_name} · {data.game_name}
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="break-words text-heading-lg">{data.name}</h1>
          <RegistrationStatusBadge status={data.registration_status} />
        </div>
      </header>
      <section
        aria-labelledby="team-invite-heading"
        className="flex flex-col gap-3"
      >
        <h2 id="team-invite-heading" className="text-heading-md">
          邀請隊友
        </h2>
        <InviteLinkField
          label="隊伍邀請連結"
          url={teamInviteUrl(data.invite_token)}
          invalid={
            data.invite_status === "full" ? { reason: TEAM_FULL_REASON } : null
          }
          note={
            data.invite_status === "full"
              ? undefined
              : "隊友開啟連結、登入並完成 Email 驗證後即可加入。"
          }
        />
      </section>
      <section
        aria-labelledby="team-roster-heading"
        className="flex flex-col gap-3"
      >
        <h2 id="team-roster-heading" className="text-heading-md">
          隊伍名單
        </h2>
        <RosterList
          members={data.members}
          starters={data.starters}
          maxMembers={data.max_members}
        />
      </section>
    </section>
  )
}
