# Animeko Ads Clear

基於 [open-ani/animeko](https://github.com/open-ani/animeko) 的輕量補丁版本。此儲存庫不複製上游原始碼，而是在建構時取得指定的官方版本並套用 [`noad.patch`](noad.patch)。

## 修改內容

- 過濾播放頁「相關推薦」中帶外部連結或無有效 `subjectId` 的廣告項目。
- 停用應用程式內的官方更新檢查，避免自行建構版本被官方套件覆蓋。

此補丁不會移除影片串流本身內嵌的廣告，也不修改資料源、播放器或其他介面。

## 支援平台

| 平台 | 架構 | Actions 產物 |
| --- | --- | --- |
| Android 手機 | arm64-v8a、armeabi-v7a、x86_64、universal | 已簽署 APK |
| Android TV | arm64-v8a、armeabi-v7a、x86_64、universal | 已簽署 APK |
| Windows | x86_64、ARM64 | ZIP |
| macOS | Apple Silicon、Intel | DMG／ZIP |
| Linux | x86_64 | AppImage |
| iOS／iPadOS | ARM64 | 未簽署 IPA |

桌面產物沒有開發者憑證簽署或公證。iOS IPA 需要使用自己的 Apple 憑證另行簽署。

iOS Kotlin/Native linking 的記憶體需求明顯高於其他平台。Workflow 會使用上游的高記憶體 JVM 設定並自動重試；若 GitHub 標準 macOS runner 仍無法完成，iOS 會標記為實驗性失敗，Android 簽章與其他平台 Release 仍會繼續。

## 自動建構與發佈

Workflow 每 6 小時檢查一次 Animeko 最新穩定版。若本儲存庫尚未建立對應的 `vX.Y.Z-noad` Release，便會自動建構所有平台、簽署 Android APK，並建立 GitHub Release；已有相同版本時會略過，避免重複建構。

修改 `noad.patch`、workflow 或 `scripts/` 建構工具並推送至 `noad-ci` 時，也會自動建構尚未發佈的目前上游版本。

也可以到 **Actions → noad multiplatform → Run workflow** 手動執行。`tag` 留空會選擇最新穩定版，也可以指定版本，例如 `v6.2.0`。手動重建已存在的版本時仍會產生 Actions artifacts，但不會覆蓋既有 Release。

每個平台的 Actions artifact 會保留 14 天。Release 與 artifacts 包含 SHA-256、來源版本資訊與實際套用的差異。

## GitHub Secrets

在 **Settings → Secrets and variables → Actions → Secrets** 新增：

彈彈play 彈幕：

| Secret | 內容 |
| --- | --- |
| `DANDANPLAY_APP_ID` | 在[彈彈play開發者中心](https://dev.dandanplay.com/)取得的 App ID |
| `DANDANPLAY_APP_SECRET` | 對應的 App Secret |

這兩項必須同時設定。Workflow 會把它們寫入上游要求的 `local.properties` 建構參數；沒有設定時仍可完成建構，但彈彈play彈幕不可用。請使用本專案專用的憑證，切勿把值寫進儲存庫或 Actions log。

Android 正式簽章：

| Secret | 內容 |
| --- | --- |
| `SIGNING_RELEASE_STOREFILE` | JKS／keystore 檔案的 Base64 內容 |
| `SIGNING_RELEASE_STOREPASSWORD` | keystore 密碼 |
| `SIGNING_RELEASE_KEYALIAS` | key alias |
| `SIGNING_RELEASE_KEYPASSWORD` | 私鑰密碼 |

在 PowerShell 產生 Base64：

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes('C:\path\release.jks')) | Set-Clipboard
```

請持續使用同一組 keystore，否則 Android 無法直接升級既有安裝。官方 Animeko 與本專案若使用不同簽章，也無法彼此覆蓋安裝。

彈彈play 憑證必須在建構時嵌入用戶端，因此 Gradle／Xcode 會讀取它們。Android keystore 仍與上游建構隔離：APK 會先以無簽章 artifact 交給獨立工作，再由該工作解碼臨時 keystore、簽署並驗證。臨時 keystore 不會上傳至 artifact。

## 本機建構 Android 手機 Debug APK

準備 JBR 21（含 JCEF）、Android SDK platform 37.0 與 build-tools 36.0.0，取得 Animeko 原始碼後套用補丁：

```powershell
git apply C:\path\animeko-ads-clear\noad.patch
```

在上游專案的 `local.properties` 設定 Android SDK、ABI 與 Debug 套件名稱：

```properties
sdk.dir=C\:\\Android\\Sdk
ani.android.abis=all
ani.android.debug.applicationIdSuffix=.noad.debug
ani.enable.firebase=false
```

只建構手機版：

```powershell
.\gradlew.bat :app:android:assembleDefaultDebug
```

APK 位於 `app/android/build/outputs/apk/default/debug/`。不要使用 `assembleDebug`，因為它也會建構 Android TV 版本。

## 已知限制

- 未設定 `DANDANPLAY_APP_ID` 與 `DANDANPLAY_APP_SECRET` 時，Actions 產物無法使用彈彈play彈幕來源。
- Firebase 預設停用。
- 補丁以 Animeko `v6.2.0` 驗證；上游結構改變而無法套用時，workflow 會直接失敗。
- 各平台仍需實機驗證。完整設計與維護紀錄請見 [`PROJECT.md`](PROJECT.md)。

## 授權

沿用上游的 [AGPL-3.0](https://github.com/open-ani/animeko/blob/main/LICENSE)。對應原始碼由指定的 Animeko tag、本儲存庫補丁與建構腳本共同構成。

