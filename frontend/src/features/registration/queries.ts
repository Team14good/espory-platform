import { queryOptions } from "@tanstack/react-query"

import { RegistrationService } from "@/client"

/** registration 相關 query 的共同前綴。 */
export const REGISTRATION_QUERY_KEY = ["registration"] as const

export const teamQueryOptions = (teamId: string) =>
  queryOptions({
    queryKey: [...REGISTRATION_QUERY_KEY, "team", teamId],
    queryFn: async () =>
      (await RegistrationService.readTeam({ path: { team_id: teamId } })).data,
  })

export const myTeamsQueryOptions = () =>
  queryOptions({
    queryKey: [...REGISTRATION_QUERY_KEY, "my-teams"],
    queryFn: async () => (await RegistrationService.listMyTeams()).data,
  })

export const teamInviteQueryOptions = (token: string) =>
  queryOptions({
    queryKey: [...REGISTRATION_QUERY_KEY, "invite", token],
    queryFn: async () =>
      (await RegistrationService.previewTeamInvite({ path: { token } })).data,
  })

/** S19 的邀請連結（完整網址）；S17 的 Invite link field 顯示這個。 */
export function teamInviteUrl(token: string): string {
  return `${window.location.origin}/join/${encodeURIComponent(token)}`
}
