import { screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import {
  type Identity,
  type MyTeamCard,
  RegistrationService,
  type TeamDetail,
  type TeamInvitePreview,
} from "@/client"
import { ACCOUNT, BROWSE, renderApp, signInAs } from "./auth-fixtures"
import { httpError } from "./helpers"

vi.mock("@tanstack/react-router-devtools", () => ({
  TanStackRouterDevtools: () => null,
}))
vi.mock("@tanstack/react-query-devtools", () => ({
  ReactQueryDevtools: () => null,
}))

type ReadTeamResult = Awaited<ReturnType<typeof RegistrationService.readTeam>>
type PreviewResult = Awaited<
  ReturnType<typeof RegistrationService.previewTeamInvite>
>
type JoinResult = Awaited<ReturnType<typeof RegistrationService.joinTeam>>
type MyTeamsResult = Awaited<ReturnType<typeof RegistrationService.listMyTeams>>

const MY_TEAMS: Identity = {
  key: "my_teams",
  label: "我的隊伍",
  home_path: "/me/teams",
}

const member = (
  id: string,
  name: string,
  role: "captain" | "player" = "player",
) => ({
  account_id: id,
  display_name: name,
  role,
  joined_at: "2026-10-30T10:00:00Z",
})

const TEAM: TeamDetail = {
  id: "team-1",
  name: "夜貓隊",
  tournament_id: "tour-1",
  tournament_name: "政大校園盃",
  game_name: "特戰英豪",
  starters: 5,
  substitutes: 1,
  max_members: 6,
  members: [
    member("acc-1", "阿哲", "captain"),
    member("acc-2", "小芸"),
    member("acc-3", "阿凱"),
    member("acc-4", "小晴"),
  ],
  registration_status: "forming",
  invite_token: "tok-1",
  invite_status: "active",
  my_role: "player",
}

const INVITE: TeamInvitePreview = {
  team_id: "team-1",
  team_name: "夜貓隊",
  tournament_id: "tour-1",
  tournament_name: "政大校園盃",
  game_name: "特戰英豪",
  member_count: 4,
  max_members: 6,
  invite_status: "active",
}

function mockReadTeam(team: TeamDetail = TEAM) {
  return vi
    .spyOn(RegistrationService, "readTeam")
    .mockResolvedValue({ data: team } as ReadTeamResult)
}

function mockPreview(invite: TeamInvitePreview = INVITE) {
  return vi
    .spyOn(RegistrationService, "previewTeamInvite")
    .mockResolvedValue({ data: invite } as PreviewResult)
}

describe("隊伍頁（S17）", () => {
  it("隊員檢視：名單、隊長徽章、人數與邀請連結", async () => {
    signInAs()
    const read = mockReadTeam()
    renderApp("/teams/team-1")

    expect(
      await screen.findByRole("heading", { name: "夜貓隊" }),
    ).toBeInTheDocument()
    expect(read).toHaveBeenCalledWith({ path: { team_id: "team-1" } })
    expect(screen.getByText("政大校園盃 · 特戰英豪")).toBeInTheDocument()
    expect(screen.getByText("組隊中")).toBeInTheDocument()

    const rows = within(
      screen.getByRole("list", { name: "隊伍名單" }),
    ).getAllByRole("listitem")
    expect(rows).toHaveLength(4)
    expect(within(rows[0]).getByText("隊長")).toBeInTheDocument()
    expect(screen.getByText("4／6 人（先發 5）")).toBeInTheDocument()

    expect(screen.getByLabelText("隊伍邀請連結")).toHaveValue(
      `${window.location.origin}/join/tok-1`,
    )
    expect(screen.getByRole("button", { name: "複製連結" })).toBeEnabled()
  })

  it("額滿時邀請連結顯示「連結已失效」與原因「隊伍已滿」", async () => {
    signInAs()
    mockReadTeam({
      ...TEAM,
      max_members: 4,
      substitutes: 0,
      starters: 4,
      invite_status: "full",
    })
    renderApp("/teams/team-1")

    expect(await screen.findByText("連結已失效")).toBeInTheDocument()
    expect(screen.getByText(/隊伍已滿/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "複製連結" })).toBeDisabled()
  })

  it("非隊員：顯示沒有權限", async () => {
    signInAs()
    vi.spyOn(RegistrationService, "readTeam").mockRejectedValue(
      httpError(403, {
        detail: {
          code: "TEAM_MEMBER_REQUIRED",
          message: "只有隊員可以查看這支隊伍。",
        },
      }),
    )
    renderApp("/teams/team-1")

    expect(
      await screen.findByText("你沒有權限查看這個頁面。"),
    ).toBeInTheDocument()
  })

  it("未登入：導向登入並帶 redirect 回隊伍頁", async () => {
    const router = renderApp("/teams/team-1")

    await waitFor(() => expect(router.state.location.pathname).toBe("/login"))
    expect(router.state.location.search).toEqual({ redirect: "/teams/team-1" })
  })
})

describe("加入隊伍（S19）", () => {
  it("未登入：先顯示賽事、遊戲與隊名，提供註冊與登入（帶 redirect 回 S19）", async () => {
    mockPreview()
    renderApp("/join/tok-1")

    expect(await screen.findByText("政大校園盃 · 特戰英豪")).toBeInTheDocument()
    expect(screen.getByText("夜貓隊")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "註冊帳號" })).toHaveAttribute(
      "href",
      "/signup?redirect=%2Fjoin%2Ftok-1",
    )
    expect(screen.getByRole("link", { name: "登入帳號" })).toHaveAttribute(
      "href",
      "/login?redirect=%2Fjoin%2Ftok-1",
    )
    expect(screen.queryByRole("button", { name: "加入隊伍" })).toBeNull()
  })

  it("未驗證 Email：說明需先驗證，「加入隊伍」停用", async () => {
    signInAs({ account: { ...ACCOUNT, email_verified: false } })
    mockPreview()
    renderApp("/join/tok-1")

    expect(
      await screen.findByText("完成 Email 驗證後才能加入隊伍。"),
    ).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "加入隊伍" })).toBeDisabled()
  })

  it("加入成功後到隊伍頁", async () => {
    const user = userEvent.setup()
    signInAs()
    mockPreview()
    const join = vi
      .spyOn(RegistrationService, "joinTeam")
      .mockResolvedValue({ data: TEAM } as JoinResult)
    mockReadTeam()
    const router = renderApp("/join/tok-1")

    const button = await screen.findByRole("button", { name: "加入隊伍" })
    await waitFor(() => expect(button).toBeEnabled())
    await user.click(button)

    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/teams/team-1"),
    )
    expect(join).toHaveBeenCalledWith({ path: { token: "tok-1" } })
  })

  it("被拒絕時說明原因並提供回賽事頁的連結", async () => {
    const user = userEvent.setup()
    signInAs()
    mockPreview()
    vi.spyOn(RegistrationService, "joinTeam").mockRejectedValue(
      httpError(409, {
        detail: {
          code: "ALREADY_IN_TOURNAMENT",
          message: "你已經在這個賽事的隊伍中，同一個賽事只能加入一支隊伍。",
        },
      }),
    )
    renderApp("/join/tok-1")

    const button = await screen.findByRole("button", { name: "加入隊伍" })
    await waitFor(() => expect(button).toBeEnabled())
    await user.click(button)

    expect(
      await screen.findByText(
        "你已經在這個賽事的隊伍中，同一個賽事只能加入一支隊伍。",
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "回到賽事頁" })).toHaveAttribute(
      "href",
      "/tournaments/tour-1",
    )
    // 已在同賽事的隊伍：另提供「查看我的隊伍」
    expect(screen.getByRole("link", { name: "查看我的隊伍" })).toHaveAttribute(
      "href",
      "/me/teams",
    )
  })

  it("加入成功或失敗後重新取得邀請預覽；其他原因被拒時不顯示「查看我的隊伍」", async () => {
    const user = userEvent.setup()
    signInAs()
    const preview = mockPreview()
    vi.spyOn(RegistrationService, "joinTeam").mockRejectedValue(
      httpError(409, {
        detail: { code: "TEAM_FULL", message: "隊伍已滿，無法再加入。" },
      }),
    )
    renderApp("/join/tok-1")

    const button = await screen.findByRole("button", { name: "加入隊伍" })
    await waitFor(() => expect(button).toBeEnabled())
    expect(preview).toHaveBeenCalledTimes(1)
    await user.click(button)

    expect(
      await screen.findByText("隊伍已滿，無法再加入。"),
    ).toBeInTheDocument()
    await waitFor(() => expect(preview).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole("link", { name: "查看我的隊伍" })).toBeNull()
  })

  it("隊伍已滿：說明連結已失效，不提供加入", async () => {
    signInAs()
    mockPreview({ ...INVITE, member_count: 6, invite_status: "full" })
    renderApp("/join/tok-1")

    expect(
      await screen.findByText("連結已失效：隊伍已滿。"),
    ).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "加入隊伍" })).toBeNull()
    expect(screen.getByRole("link", { name: "回到賽事頁" })).toHaveAttribute(
      "href",
      "/tournaments/tour-1",
    )
  })

  it("連結不存在：說明連結無效", async () => {
    vi.spyOn(RegistrationService, "previewTeamInvite").mockRejectedValue(
      httpError(404, {
        detail: {
          code: "TEAM_INVITE_NOT_FOUND",
          message: "這個邀請連結無效。",
        },
      }),
    )
    renderApp("/join/nope")

    expect(await screen.findByText(/這個邀請連結無效。/)).toBeInTheDocument()
  })
})

describe("我的隊伍（S12）", () => {
  it("每隊一張 Registration status card，點擊到 S17", async () => {
    const user = userEvent.setup()
    signInAs()
    const cards: MyTeamCard[] = [
      {
        team_id: "team-1",
        team_name: "夜貓隊",
        tournament_id: "tour-1",
        tournament_name: "政大校園盃",
        game_name: "特戰英豪",
        registration_status: "forming",
      },
    ]
    vi.spyOn(RegistrationService, "listMyTeams").mockResolvedValue({
      data: cards,
    } as MyTeamsResult)
    mockReadTeam()
    const router = renderApp("/me/teams")

    const card = await screen.findByRole("link", { name: /夜貓隊/ })
    expect(card).toHaveAttribute("href", "/teams/team-1")
    expect(within(card).getByText("政大校園盃 · 特戰英豪")).toBeInTheDocument()
    expect(within(card).getByText("組隊中")).toBeInTheDocument()

    await user.click(card)

    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/teams/team-1"),
    )
  })

  it("沒有隊伍：「你還沒有加入任何隊伍。」＋「瀏覽賽事」", async () => {
    signInAs()
    vi.spyOn(RegistrationService, "listMyTeams").mockResolvedValue({
      data: [],
    } as unknown as MyTeamsResult)
    renderApp("/me/teams")

    expect(
      await screen.findByText("你還沒有加入任何隊伍。"),
    ).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "瀏覽賽事" })).toHaveAttribute(
      "href",
      "/",
    )
  })

  it("身分切換器出現「我的隊伍」，點選到 /me/teams", async () => {
    const user = userEvent.setup()
    signInAs({ identities: [BROWSE, MY_TEAMS] })
    vi.spyOn(RegistrationService, "listMyTeams").mockResolvedValue({
      data: [],
    } as unknown as MyTeamsResult)
    const router = renderApp("/")

    const banner = await screen.findByRole("banner")
    await user.click(
      await within(banner).findByRole("button", { name: /切換身分（目前：/ }),
    )
    const menu = await screen.findByRole("menu")
    await user.click(within(menu).getByRole("menuitem", { name: /我的隊伍/ }))

    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/me/teams"),
    )
  })
})
