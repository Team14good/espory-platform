// 截圖檔案的前端檢查，規則與後端 core.storage 相同（AD-15）：
// 只收 JPG／PNG、5 MB（5 × 1024 × 1024 bytes）以內。伺服器仍會再驗一次檔頭與大小。

export const MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
export const ACCEPTED_SCREENSHOT_TYPES = ["image/jpeg", "image/png"] as const

export const UNSUPPORTED_SCREENSHOT_MESSAGE = "只接受 JPG 或 PNG 圖片"
export const SCREENSHOT_TOO_LARGE_MESSAGE = "圖片不能超過 5 MB"

/** 檔案合格時回傳 null，否則回傳要顯示給使用者的錯誤訊息。 */
export function validateScreenshotFile(
  file: Pick<File, "type" | "size">,
): string | null {
  if (
    !(ACCEPTED_SCREENSHOT_TYPES as readonly string[]).includes(
      file.type.toLowerCase(),
    )
  ) {
    return UNSUPPORTED_SCREENSHOT_MESSAGE
  }
  if (file.size > MAX_SCREENSHOT_BYTES) {
    return SCREENSHOT_TOO_LARGE_MESSAGE
  }
  return null
}
