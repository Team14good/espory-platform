import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  GAME_ID_HINT,
  PlayerProfileDialog,
  type PlayerProfileDialogProps,
} from "@/features/registration/PlayerProfileDialog"

const RANK_TIERS = [
  { name: "鑽石", score: 50 },
  { name: "白金", score: 40 },
  { name: "黃金", score: 30 },
]

const DESKTOP_WIDTH = window.innerWidth

function setViewport(width: number) {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    writable: true,
    value: width,
  })
}

beforeEach(() => {
  // jsdom 沒有 matchMedia；useIsMobile 只用它監聽變化，寬度看 innerWidth
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
  URL.createObjectURL = vi.fn(() => "blob:preview")
  URL.revokeObjectURL = vi.fn()
})

afterEach(() => {
  setViewport(DESKTOP_WIDTH)
})

function renderDialog(props: Partial<PlayerProfileDialogProps> = {}) {
  const onSubmit = vi.fn<PlayerProfileDialogProps["onSubmit"]>(() =>
    Promise.resolve(),
  )
  render(
    <PlayerProfileDialog
      open
      onOpenChange={() => {}}
      rankTiers={RANK_TIERS}
      onSubmit={onSubmit}
      {...props}
    />,
  )
  return { onSubmit }
}

function businessError(status: number, code: string, message: string) {
  return {
    isAxiosError: true,
    response: { status, data: { detail: { code, message } } },
  }
}

function pngFile(name = "rank.png") {
  return new File(["png"], name, { type: "image/png" })
}

describe("S18 選手參賽資料", () => {
  it("桌機以 Dialog 呈現，並提示上場要用這個遊戲 ID", () => {
    setViewport(1280)
    renderDialog()

    expect(screen.getByTestId("player-profile-dialog")).toBeInTheDocument()
    expect(screen.queryByTestId("player-profile-sheet")).toBeNull()
    expect(screen.getByText(GAME_ID_HINT)).toBeInTheDocument()
  })

  it("手機寬度（< 768px）以 Sheet 呈現", () => {
    setViewport(375)
    renderDialog()

    expect(screen.getByTestId("player-profile-sheet")).toBeInTheDocument()
    expect(screen.queryByTestId("player-profile-dialog")).toBeNull()
  })

  it("段位選項只來自賽事的對照表", async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(screen.getByRole("combobox", { name: "段位" }))

    const options = await screen.findAllByRole("option")
    expect(options.map((option) => option.textContent)).toEqual([
      "鑽石",
      "白金",
      "黃金",
    ])
  })

  it("填完送出：遊戲 ID 去頭尾空白，帶出段位與新選的截圖", async () => {
    const user = userEvent.setup()
    const { onSubmit } = renderDialog()
    const screenshot = pngFile()

    await user.type(screen.getByLabelText("遊戲 ID"), "  Faker#TW1  ")
    await user.click(screen.getByRole("combobox", { name: "段位" }))
    await user.click(await screen.findByRole("option", { name: "白金" }))
    await user.upload(screen.getByLabelText("段位截圖"), screenshot)
    expect(
      screen.getByRole("img", { name: "rank.png 預覽" }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "儲存資料" }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit.mock.calls[0][0]).toEqual({
      game_account_id: "Faker#TW1",
      rank_tier: "白金",
      rank_screenshot: screenshot,
    })
  })

  it("沒填就送出：逐欄顯示錯誤，不呼叫 onSubmit", async () => {
    const user = userEvent.setup()
    const { onSubmit } = renderDialog()

    await user.type(screen.getByLabelText("遊戲 ID"), "   ")
    await user.click(screen.getByRole("button", { name: "儲存資料" }))

    expect(await screen.findByText("請輸入遊戲 ID")).toBeInTheDocument()
    expect(screen.getByText("請選擇段位")).toBeInTheDocument()
    expect(screen.getByText("請選擇段位截圖")).toHaveClass("text-destructive")
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it("已上傳過截圖：重開只顯示「已上傳」＋檔名、沒有圖片，不必重選即可送出", async () => {
    const user = userEvent.setup()
    const { onSubmit } = renderDialog({
      initialValues: { game_account_id: "Faker#TW1", rank_tier: "鑽石" },
      uploadedScreenshotName: "my-rank.png",
    })

    expect(screen.getByLabelText("遊戲 ID")).toHaveValue("Faker#TW1")
    expect(screen.getByRole("combobox", { name: "段位" })).toHaveTextContent(
      "鑽石",
    )
    expect(screen.getByTestId("screenshot-uploaded")).toHaveTextContent(
      "已上傳",
    )
    expect(screen.getByTestId("screenshot-uploaded")).toHaveTextContent(
      "my-rank.png",
    )
    expect(screen.queryByRole("img")).toBeNull()

    await user.click(screen.getByRole("button", { name: "儲存資料" }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit.mock.calls[0][0]).toEqual({
      game_account_id: "Faker#TW1",
      rank_tier: "鑽石",
      rank_screenshot: null,
    })
  })

  it("唯讀（名單鎖定）：所有欄位停用，沒有「儲存資料」", () => {
    renderDialog({
      readOnly: true,
      initialValues: { game_account_id: "Faker#TW1", rank_tier: "鑽石" },
      uploadedScreenshotName: "my-rank.png",
    })

    expect(screen.getByLabelText("遊戲 ID")).toBeDisabled()
    expect(screen.getByRole("combobox", { name: "段位" })).toBeDisabled()
    expect(screen.getByLabelText("段位截圖")).toBeDisabled()
    expect(screen.queryByRole("button", { name: "更換圖片" })).toBeNull()
    expect(screen.queryByRole("button", { name: "儲存資料" })).toBeNull()
  })

  it("伺服器回段位不在對照表（422）：錯誤顯示在段位欄下方", async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn(() =>
      Promise.reject({
        isAxiosError: true,
        response: {
          status: 422,
          data: {
            detail: [
              {
                type: "RANK_TIER_NOT_ALLOWED",
                loc: ["body", "rank_tier"],
                msg: "段位必須是賽事段位對照表中的段位",
              },
            ],
          },
        },
      }),
    )
    renderDialog({
      onSubmit,
      initialValues: { game_account_id: "Faker#TW1", rank_tier: "鑽石" },
      uploadedScreenshotName: "my-rank.png",
    })

    await user.click(screen.getByRole("button", { name: "儲存資料" }))

    expect(
      await screen.findByText("段位必須是賽事段位對照表中的段位"),
    ).toHaveAttribute("data-slot", "form-message")
    expect(screen.getByRole("combobox", { name: "段位" })).toHaveAttribute(
      "aria-invalid",
      "true",
    )
  })

  it("伺服器回 415：錯誤顯示在截圖欄下方，不在表單頂部", async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn(() =>
      Promise.reject(
        businessError(415, "UNSUPPORTED_FILE_TYPE", "只接受 JPG 或 PNG 圖片"),
      ),
    )
    renderDialog({
      onSubmit,
      initialValues: { game_account_id: "Faker#TW1", rank_tier: "鑽石" },
      uploadedScreenshotName: "my-rank.png",
    })

    await user.click(screen.getByRole("button", { name: "儲存資料" }))

    expect(await screen.findByText("只接受 JPG 或 PNG 圖片")).toHaveClass(
      "text-destructive",
    )
    expect(screen.getByTestId("screenshot-uploaded")).toHaveClass(
      "border-destructive",
    )
    expect(screen.queryByRole("alert")).toBeNull()
  })

  it("關閉再開啟：回到已儲存的資料，清掉沒送出的輸入、截圖與錯誤", async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn(() =>
      Promise.reject(businessError(409, "ROSTER_LOCKED", "名單已鎖定")),
    )
    const props = {
      onOpenChange: () => {},
      rankTiers: RANK_TIERS,
      onSubmit,
      initialValues: { game_account_id: "Faker#TW1", rank_tier: "鑽石" },
      uploadedScreenshotName: "my-rank.png",
    }
    const { rerender } = render(<PlayerProfileDialog open {...props} />)

    const gameId = screen.getByLabelText("遊戲 ID")
    await user.clear(gameId)
    await user.type(gameId, "Other#TW2")
    await user.click(screen.getByRole("button", { name: "更換圖片" }))
    await user.upload(screen.getByLabelText("段位截圖"), pngFile("new.png"))
    expect(
      screen.getByRole("img", { name: "new.png 預覽" }),
    ).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "儲存資料" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("名單已鎖定")

    rerender(<PlayerProfileDialog open={false} {...props} />)
    rerender(<PlayerProfileDialog open {...props} />)

    expect(screen.getByLabelText("遊戲 ID")).toHaveValue("Faker#TW1")
    expect(screen.queryByRole("img")).toBeNull()
    expect(screen.getByTestId("screenshot-uploaded")).toHaveTextContent(
      "my-rank.png",
    )
    expect(screen.queryByRole("alert")).toBeNull()
  })

  it("開著時父層更新 initialValues：不洗掉正在輸入的內容", async () => {
    const user = userEvent.setup()
    const props = {
      onOpenChange: () => {},
      rankTiers: RANK_TIERS,
      onSubmit: () => Promise.resolve(),
    }
    const { rerender } = render(
      <PlayerProfileDialog
        open
        {...props}
        initialValues={{ game_account_id: "A" }}
      />,
    )
    await user.type(screen.getByLabelText("遊戲 ID"), "BC")

    rerender(
      <PlayerProfileDialog
        open
        {...props}
        initialValues={{ game_account_id: "Z" }}
      />,
    )

    expect(screen.getByLabelText("遊戲 ID")).toHaveValue("ABC")
  })

  it("上傳中：顯示進度", () => {
    renderDialog({ uploadProgress: 42 })

    expect(screen.getByText("上傳中 42%")).toBeInTheDocument()
  })
})
