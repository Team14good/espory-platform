import { fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  ScreenshotUploader,
  type ScreenshotUploaderProps,
} from "@/features/registration/ScreenshotUploader"
import {
  MAX_SCREENSHOT_BYTES,
  SCREENSHOT_TOO_LARGE_MESSAGE,
  UNSUPPORTED_SCREENSHOT_MESSAGE,
  validateScreenshotFile,
} from "@/features/registration/screenshot-file"

function imageFile(name: string, type: string, size = 1024): File {
  const file = new File(["x"], name, { type })
  Object.defineProperty(file, "size", { value: size })
  return file
}

function Harness(
  props: Omit<ScreenshotUploaderProps, "value" | "onChange"> & {
    initial?: File | null
  },
) {
  const { initial = null, ...rest } = props
  const [value, setValue] = useState<File | null>(initial)
  return (
    <>
      <ScreenshotUploader
        id="shot"
        value={value}
        onChange={setValue}
        {...rest}
      />
      <output data-testid="value">選取：{value?.name ?? "none"}</output>
    </>
  )
}

function fileInput(): HTMLInputElement {
  const input = document.querySelector<HTMLInputElement>("input[type=file]")
  if (!input) throw new Error("找不到檔案欄位")
  return input
}

const createObjectURL = vi.fn(() => "blob:preview")
const revokeObjectURL = vi.fn()

beforeEach(() => {
  createObjectURL.mockClear()
  revokeObjectURL.mockClear()
  URL.createObjectURL = createObjectURL
  URL.revokeObjectURL = revokeObjectURL
})

afterEach(() => {
  // @ts-expect-error jsdom 原本沒有這兩個函式
  delete URL.createObjectURL
  // @ts-expect-error jsdom 原本沒有這兩個函式
  delete URL.revokeObjectURL
})

describe("validateScreenshotFile", () => {
  it("JPG、PNG 在 5 MB 以內可收；剛好 5 MB 可收", () => {
    expect(validateScreenshotFile({ type: "image/png", size: 10 })).toBeNull()
    expect(
      validateScreenshotFile({
        type: "image/jpeg",
        size: MAX_SCREENSHOT_BYTES,
      }),
    ).toBeNull()
  })

  it("其他格式或多 1 byte 拒絕", () => {
    expect(validateScreenshotFile({ type: "image/gif", size: 10 })).toBe(
      UNSUPPORTED_SCREENSHOT_MESSAGE,
    )
    expect(validateScreenshotFile({ type: "", size: 10 })).toBe(
      UNSUPPORTED_SCREENSHOT_MESSAGE,
    )
    expect(
      validateScreenshotFile({
        type: "image/png",
        size: MAX_SCREENSHOT_BYTES + 1,
      }),
    ).toBe(SCREENSHOT_TOO_LARGE_MESSAGE)
  })
})

describe("Screenshot uploader", () => {
  it("選了合格圖片：顯示縮圖、檔名與移除鈕；移除後回到拖放區，可以重選", async () => {
    const user = userEvent.setup()
    render(<Harness />)

    await user.upload(fileInput(), imageFile("rank.png", "image/png"))

    expect(screen.getByRole("img", { name: "rank.png 預覽" })).toHaveAttribute(
      "src",
      "blob:preview",
    )
    expect(screen.getByText("rank.png")).toBeInTheDocument()
    expect(screen.queryByTestId("screenshot-dropzone")).toBeNull()

    await user.click(screen.getByRole("button", { name: "移除截圖" }))

    expect(screen.queryByRole("img")).toBeNull()
    expect(screen.getByTestId("screenshot-dropzone")).toBeInTheDocument()
    expect(screen.getByTestId("value")).toHaveTextContent("none")
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:preview")

    await user.upload(fileInput(), imageFile("again.jpg", "image/jpeg"))
    expect(screen.getByTestId("value")).toHaveTextContent("again.jpg")
  })

  it("選 GIF：不顯示預覽，外框與說明文字用 destructive", async () => {
    const user = userEvent.setup({ applyAccept: false })
    render(<Harness />)

    await user.upload(fileInput(), imageFile("rank.gif", "image/gif"))

    expect(screen.queryByRole("img")).toBeNull()
    expect(screen.getByTestId("value")).toHaveTextContent("none")
    const message = screen.getByText(UNSUPPORTED_SCREENSHOT_MESSAGE)
    expect(message).toHaveClass("text-destructive")
    expect(screen.getByTestId("screenshot-dropzone")).toHaveClass(
      "border-destructive",
    )
    expect(fileInput()).toHaveAttribute("aria-invalid", "true")
  })

  it("選 6 MB 的 PNG：顯示大小錯誤；之後選合格的檔案錯誤消失", async () => {
    const user = userEvent.setup()
    render(<Harness />)

    await user.upload(
      fileInput(),
      imageFile("big.png", "image/png", 6 * 1024 * 1024),
    )

    expect(screen.getByText(SCREENSHOT_TOO_LARGE_MESSAGE)).toHaveClass(
      "text-destructive",
    )
    expect(screen.queryByRole("img")).toBeNull()

    await user.upload(fileInput(), imageFile("ok.png", "image/png"))

    expect(screen.queryByText(SCREENSHOT_TOO_LARGE_MESSAGE)).toBeNull()
    expect(screen.getByRole("img", { name: "ok.png 預覽" })).toBeInTheDocument()
  })

  it("拖放圖片到拖放區：與選檔相同", () => {
    render(<Harness />)
    const zone = screen.getByTestId("screenshot-dropzone")

    fireEvent.dragOver(zone, { dataTransfer: { files: [] } })
    expect(zone).toHaveAttribute("data-dragging", "true")
    fireEvent.drop(zone, {
      dataTransfer: { files: [imageFile("drop.png", "image/png")] },
    })

    expect(screen.getByTestId("value")).toHaveTextContent("drop.png")
    expect(
      screen.getByRole("img", { name: "drop.png 預覽" }),
    ).toBeInTheDocument()
  })

  it("拖放錯誤格式：顯示錯誤", () => {
    render(<Harness />)

    fireEvent.drop(screen.getByTestId("screenshot-dropzone"), {
      dataTransfer: { files: [imageFile("a.webp", "image/webp")] },
    })

    expect(screen.getByText(UNSUPPORTED_SCREENSHOT_MESSAGE)).toBeInTheDocument()
    expect(screen.getByTestId("value")).toHaveTextContent("none")
  })

  it("已上傳：只顯示「已上傳」＋檔名，不顯示圖片", () => {
    render(<Harness uploadedFileName="my-rank.png" />)

    const uploaded = screen.getByTestId("screenshot-uploaded")
    expect(uploaded).toHaveTextContent("已上傳")
    expect(uploaded).toHaveTextContent("my-rank.png")
    expect(screen.queryByRole("img")).toBeNull()
    expect(createObjectURL).not.toHaveBeenCalled()
    expect(screen.getByRole("button", { name: "更換圖片" })).toBeEnabled()
  })

  it("上傳中：顯示進度條與百分比，不能移除", () => {
    render(
      <Harness initial={imageFile("rank.png", "image/png")} progress={42} />,
    )

    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "42",
    )
    expect(screen.getByText("上傳中 42%")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "移除截圖" })).toBeDisabled()
    // 上傳中拖放新檔也不會換掉
    fireEvent.drop(screen.getByTestId("screenshot-preview"), {
      dataTransfer: { files: [imageFile("other.png", "image/png")] },
    })
    expect(screen.getByTestId("value")).toHaveTextContent("rank.png")
  })

  it("上傳中：不能選擇或更換圖片", () => {
    const { rerender } = render(<Harness progress={10} />)
    expect(screen.getByRole("button", { name: "選擇圖片" })).toBeDisabled()

    rerender(<Harness progress={10} uploadedFileName="my-rank.png" />)
    expect(screen.getByRole("button", { name: "更換圖片" })).toBeDisabled()
  })

  it("進度不是有限數字時顯示 0%", () => {
    render(<Harness progress={Number.NaN} />)

    expect(screen.getByText("上傳中 0%")).toBeInTheDocument()
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "0",
    )
  })

  it("預覽列可以拖放新檔替換；移到子元素上不取消醒目提示", () => {
    render(<Harness initial={imageFile("rank.png", "image/png")} />)
    const row = screen.getByTestId("screenshot-preview")

    fireEvent.dragOver(row, { dataTransfer: { files: [] } })
    expect(row).toHaveClass("border-primary")
    // jsdom 的 DragEvent 不帶 relatedTarget，改用 MouseEvent 送出 dragleave
    const dragLeaveTo = (target: EventTarget | null) =>
      fireEvent(
        row,
        new MouseEvent("dragleave", { bubbles: true, relatedTarget: target }),
      )
    dragLeaveTo(screen.getByRole("button", { name: "移除截圖" }))
    expect(row).toHaveClass("border-primary")
    dragLeaveTo(document.body)
    expect(row).not.toHaveClass("border-primary")
    fireEvent.dragOver(row, { dataTransfer: { files: [] } })

    fireEvent.drop(row, {
      dataTransfer: { files: [imageFile("new.png", "image/png")] },
    })
    expect(screen.getByTestId("value")).toHaveTextContent("new.png")
  })

  it("外部錯誤：以 destructive 顯示", () => {
    render(<Harness error="請選擇段位截圖" />)

    expect(screen.getByText("請選擇段位截圖")).toHaveClass("text-destructive")
    expect(screen.getByTestId("screenshot-dropzone")).toHaveClass(
      "border-destructive",
    )
  })

  it("停用：按鈕與檔案欄位停用，拖放無效", () => {
    render(<Harness disabled />)

    expect(screen.getByRole("button", { name: "選擇圖片" })).toBeDisabled()
    expect(fileInput()).toBeDisabled()
    fireEvent.drop(screen.getByTestId("screenshot-dropzone"), {
      dataTransfer: { files: [imageFile("drop.png", "image/png")] },
    })
    expect(screen.getByTestId("value")).toHaveTextContent("none")
  })

  it("停用且已上傳：沒有「更換圖片」", () => {
    render(<Harness disabled uploadedFileName="my-rank.png" />)

    expect(screen.queryByRole("button", { name: "更換圖片" })).toBeNull()
  })

  it("卸載時釋放預覽的 object URL", () => {
    const { unmount } = render(
      <Harness initial={imageFile("rank.png", "image/png")} />,
    )
    expect(createObjectURL).toHaveBeenCalledTimes(1)

    unmount()

    expect(revokeObjectURL).toHaveBeenCalledWith("blob:preview")
  })
})
