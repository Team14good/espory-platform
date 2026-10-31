import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import { CircleAlertIcon } from "lucide-react"
import { RegistrationService, type TeamInvitePreview } from "@/client"
import { HrefLink } from "@/components/common/HrefLink"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { LoadingButton } from "@/components/ui/loading-button"
import { Skeleton } from "@/components/ui/skeleton"
import { useIsSignedIn } from "@/features/identity/auth"
import { VerificationRequired } from "@/features/identity/VerificationRequired"
import { getErrorMessage, parseApiError } from "@/lib/api-error"
import { notifySuccess } from "@/lib/feedback"
import {
  myTeamsQueryOptions,
  teamInviteQueryOptions,
  teamQueryOptions,
} from "./queries"
import { TEAM_FULL_REASON } from "./TeamPage"

export const JOINED_TEXT = "已加入隊伍。"
export const ALREADY_IN_TOURNAMENT = "ALREADY_IN_TOURNAMENT"
export const INVITE_NOT_FOUND_TEXT = "這個邀請連結無效。"

function isNotFound(error: unknown): boolean {
  const apiError = parseApiError(error)
  return (
    apiError.kind === "business" && apiError.code === "TEAM_INVITE_NOT_FOUND"
  )
}

/** 被拒絕或連結失效時：說明原因＋回賽事頁（S2）。 */
function Rejected({
  reason,
  tournamentId,
  showMyTeams = false,
}: {
  reason: string
  tournamentId: string
  /** 已在同賽事的隊伍（例如隊員重開自己隊伍的連結）時，另提供「查看我的隊伍」 */
  showMyTeams?: boolean
}) {
  return (
    <div className="flex flex-col items-start gap-3">
      <Alert variant="destructive" className="rounded-md">
        <CircleAlertIcon />
        <AlertDescription className="text-destructive">
          {reason}
        </AlertDescription>
      </Alert>
      <div className="flex flex-col gap-2 sm:flex-row">
        {showMyTeams && (
          <Button asChild>
            <Link to="/me/teams">查看我的隊伍</Link>
          </Button>
        )}
        <Button asChild variant="outline">
          <HrefLink href={`/tournaments/${tournamentId}`}>回到賽事頁</HrefLink>
        </Button>
      </div>
    </div>
  )
}

function JoinAction({
  token,
  invite,
}: {
  token: string
  invite: TeamInvitePreview
}) {
  const signedIn = useIsSignedIn()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const join = useMutation({
    mutationFn: async () =>
      (await RegistrationService.joinTeam({ path: { token } })).data,
    // 人數可能已改變：成功或失敗都重新取得預覽（「目前 x／y 人」）
    onSettled: () =>
      queryClient.invalidateQueries({
        queryKey: teamInviteQueryOptions(token).queryKey,
      }),
    onSuccess: (team) => {
      queryClient.setQueryData(teamQueryOptions(team.id).queryKey, team)
      queryClient.invalidateQueries({
        queryKey: myTeamsQueryOptions().queryKey,
      })
      notifySuccess(JOINED_TEXT)
      navigate({ to: "/teams/$teamId", params: { teamId: team.id } })
    },
  })

  if (invite.invite_status === "full") {
    return (
      <Rejected
        reason={`連結已失效：${TEAM_FULL_REASON}。`}
        tournamentId={invite.tournament_id}
      />
    )
  }

  if (!signedIn) {
    const redirect = `/join/${token}`
    return (
      <div className="flex flex-col gap-3">
        <p className="text-body text-muted-foreground">
          註冊或登入後即可加入這支隊伍；新註冊的帳號完成 Email
          驗證後會回到這個頁面。
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button asChild>
            <Link to="/signup" search={{ redirect }}>
              註冊帳號
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/login" search={{ redirect }}>
              登入帳號
            </Link>
          </Button>
        </div>
      </div>
    )
  }

  if (join.isError) {
    const apiError = parseApiError(join.error)
    return (
      <Rejected
        reason={getErrorMessage(apiError)}
        tournamentId={invite.tournament_id}
        showMyTeams={
          apiError.kind === "business" &&
          apiError.code === ALREADY_IN_TOURNAMENT
        }
      />
    )
  }

  return (
    <VerificationRequired action="加入隊伍">
      <LoadingButton
        type="button"
        loading={join.isPending}
        onClick={() => join.mutate()}
        className="w-full sm:w-auto sm:self-start"
      >
        加入隊伍
      </LoadingButton>
    </VerificationRequired>
  )
}

/** S19 加入隊伍：先顯示賽事、遊戲與隊名，再依登入與驗證狀態提供「加入隊伍」。 */
export function JoinTeamPage({ token }: { token: string }) {
  const invite = useQuery({ ...teamInviteQueryOptions(token), retry: false })

  return (
    <section className="mx-auto flex w-full max-w-md flex-col gap-6 py-8 sm:py-12">
      <h1 className="text-heading-lg">加入隊伍</h1>
      {invite.isPending ? (
        <div role="status" aria-busy="true" className="flex flex-col gap-3">
          <Skeleton className="h-24 w-full rounded-lg" />
          <span className="sr-only">載入中</span>
        </div>
      ) : invite.isError ? (
        isNotFound(invite.error) ? (
          <div className="flex flex-col items-start gap-3">
            <p className="text-body">
              {INVITE_NOT_FOUND_TEXT}請向隊長索取新的連結。
            </p>
            <Button asChild variant="outline">
              <Link to="/">回到首頁</Link>
            </Button>
          </div>
        ) : (
          <div className="flex flex-col items-start gap-3">
            <p className="text-body text-destructive">
              {getErrorMessage(parseApiError(invite.error))}
            </p>
            <Button variant="outline" onClick={() => invite.refetch()}>
              重新載入
            </Button>
          </div>
        )
      ) : (
        <>
          <Card className="gap-2 px-6">
            <p className="text-caption text-muted-foreground">
              {invite.data.tournament_name} · {invite.data.game_name}
            </p>
            <p className="break-words font-semibold text-heading-md">
              {invite.data.team_name}
            </p>
            <p className="text-caption text-muted-foreground">
              目前 {invite.data.member_count}／{invite.data.max_members} 人
            </p>
          </Card>
          <JoinAction token={token} invite={invite.data} />
        </>
      )}
    </section>
  )
}
