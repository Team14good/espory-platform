import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
} from "@tanstack/react-router"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { toast } from "sonner"
import { describe, expect, it, vi } from "vitest"

import { RegistrationService, type TeamDetail } from "@/client"
import { CreateTeamDialog } from "@/features/registration/CreateTeamDialog"
import {
  COPIED_TEXT,
  InviteLinkField,
} from "@/features/registration/InviteLinkField"
import { RosterList } from "@/features/registration/RosterList"
import { ACCOUNT, signInAs } from "./auth-fixtures"
import { httpError } from "./helpers"
import { renderRouter } from "./render-router"

type CreateTeamResult = Awaited<
  ReturnType<typeof RegistrationService.createTeam>
>

const URL = "http://localhost/join/tok-1"

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
    {
      account_id: "acc-1",
      display_name: "阿哲",
      role: "captain",
      joined_at: "2026-10-30T10:00:00Z",
    },
    {
      account_id: "acc-2",
      display_name: "小芸",
      role: "player",
      joined_at: "2026-10-30T10:05:00Z",
    },
    {
      account_id: "acc-3",
      display_name: "阿凱",
      role: "player",
      joined_at: "2026-10-30T10:06:00Z",
    },
    {
      account_id: "acc-4",
      display_name: "小晴",
      role: "player",
      joined_at: "2026-10-30T10:07:00Z",
    },
  ],
  registration_status: "forming",
  invite_token: "tok-1",
  invite_status: "active",
  my_role: "captain",
}

describe("Invite link field", () => {
  it("唯讀顯示連結；「複製連結」寫入剪貼簿並 Toast「已複製」", async () => {
    const user = userEvent.setup()
    const success = vi.spyOn(toast, "success")
    render(<InviteLinkField label="隊伍邀請連結" url={URL} />)

    const input = screen.getByLabelText("隊伍邀請連結")
    expect(input).toHaveValue(URL)
    expect(input).toHaveAttribute("readonly")

    await user.click(screen.getByRole("button", { name: "複製連結" }))

    expect(await navigator.clipboard.readText()).toBe(URL)
    expect(success).toHaveBeenCalledWith(COPIED_TEXT, { duration: 3000 })
  })

  it("失效時顯示「連結已失效」與原因，並停用「複製連結」", () => {
    render(
      <InviteLinkField
        label="隊伍邀請連結"
        url={URL}
        invalid={{ reason: "隊伍已滿" }}
      />,
    )

    expect(screen.getByText("連結已失效")).toBeInTheDocument()
    expect(screen.getByText(/隊伍已滿/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "複製連結" })).toBeDisabled()
    expect(screen.getByLabelText("隊伍邀請連結")).toHaveAccessibleDescription(
      /連結已失效.*隊伍已滿/,
    )
  })

  it("可改寫失效標題並顯示補充說明（裁判邀請連結沿用）", () => {
    render(
      <InviteLinkField
        label="裁判邀請連結"
        url={URL}
        invalid={{ title: "連結已過期", reason: "請產生新連結" }}
        note="11/6（五）10:00 到期"
      />,
    )

    expect(screen.getByText("連結已過期")).toBeInTheDocument()
    expect(screen.getByText("11/6（五）10:00 到期")).toBeInTheDocument()
  })
})

describe("Roster list", () => {
  it("每人一列顯示名稱，隊長有「隊長」徽章，下方顯示人數", () => {
    render(
      <RosterList
        members={TEAM.members}
        starters={TEAM.starters}
        maxMembers={TEAM.max_members}
      />,
    )

    const rows = within(
      screen.getByRole("list", { name: "隊伍名單" }),
    ).getAllByRole("listitem")
    expect(rows.map((row) => row.textContent)).toEqual([
      "阿哲隊長",
      "小芸",
      "阿凱",
      "小晴",
    ])
    expect(within(rows[0]).getByText("隊長")).toBeInTheDocument()
    expect(screen.getByText("4／6 人（先發 5）")).toBeInTheDocument()
  })
})

function renderCreateTeamDialog() {
  const rootRoute = createRootRoute({
    component: () => (
      <>
        <CreateTeamDialog tournamentId="tour-1" />
        <Outlet />
      </>
    ),
  })
  const teamRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/teams/$teamId",
    component: () => <p>隊伍頁</p>,
  })
  const router = createRouter({
    routeTree: rootRoute.addChildren([teamRoute]),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  })
  renderRouter(router)
  return router
}

describe("建立隊伍（S16）", () => {
  it("送出成功後導向該隊 S17", async () => {
    const user = userEvent.setup()
    signInAs()
    const create = vi
      .spyOn(RegistrationService, "createTeam")
      .mockResolvedValue({ data: TEAM } as CreateTeamResult)
    const router = renderCreateTeamDialog()

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "建立隊伍" })).toBeEnabled(),
    )
    await user.click(screen.getByRole("button", { name: "建立隊伍" }))
    const dialog = await screen.findByRole("dialog", { name: "建立隊伍" })
    await user.type(within(dialog).getByLabelText("隊名"), "  夜貓隊 ")
    await user.click(within(dialog).getByRole("button", { name: "建立隊伍" }))

    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/teams/team-1"),
    )
    expect(create).toHaveBeenCalledWith({
      path: { tournament_id: "tour-1" },
      body: { name: "夜貓隊" },
    })
  })

  it("隊名空白或超過 30 字時不送出", async () => {
    const user = userEvent.setup()
    signInAs()
    const create = vi.spyOn(RegistrationService, "createTeam")
    renderCreateTeamDialog()

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "建立隊伍" })).toBeEnabled(),
    )
    await user.click(screen.getByRole("button", { name: "建立隊伍" }))
    const dialog = await screen.findByRole("dialog", { name: "建立隊伍" })
    const submit = within(dialog).getByRole("button", { name: "建立隊伍" })

    await user.type(within(dialog).getByLabelText("隊名"), "   ")
    await user.click(submit)
    expect(await within(dialog).findByText("請輸入隊名")).toBeInTheDocument()

    await user.clear(within(dialog).getByLabelText("隊名"))
    await user.type(within(dialog).getByLabelText("隊名"), "隊".repeat(31))
    await user.click(submit)
    expect(
      await within(dialog).findByText("隊名最多 30 個字"),
    ).toBeInTheDocument()
    expect(create).not.toHaveBeenCalled()
  })

  it("伺服器拒絕（隊名重複）時在表單頂部顯示原因", async () => {
    const user = userEvent.setup()
    signInAs()
    vi.spyOn(RegistrationService, "createTeam").mockRejectedValue(
      httpError(409, {
        detail: {
          code: "TEAM_NAME_TAKEN",
          message: "這個賽事已經有同名的隊伍。",
        },
      }),
    )
    renderCreateTeamDialog()

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "建立隊伍" })).toBeEnabled(),
    )
    await user.click(screen.getByRole("button", { name: "建立隊伍" }))
    const dialog = await screen.findByRole("dialog", { name: "建立隊伍" })
    await user.type(within(dialog).getByLabelText("隊名"), "夜貓隊")
    await user.click(within(dialog).getByRole("button", { name: "建立隊伍" }))

    expect(
      await within(dialog).findByText("這個賽事已經有同名的隊伍。"),
    ).toBeInTheDocument()
  })

  it("Email 未驗證：「建立隊伍」停用並說明原因", async () => {
    signInAs({ account: { ...ACCOUNT, email_verified: false } })
    renderCreateTeamDialog()

    expect(
      await screen.findByText("完成 Email 驗證後才能建立隊伍。"),
    ).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "建立隊伍" })).toBeDisabled()
  })
})
