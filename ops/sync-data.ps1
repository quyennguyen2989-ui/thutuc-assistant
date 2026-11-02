# Đồng bộ dữ liệu tra cứu từ GitHub Pages về máy chủ.
# Chạy hằng ngày bằng tác vụ đã lên lịch. Chỉ ghi đè khi dữ liệu thật sự thay đổi,
# và luôn sao lưu bản cũ trước khi ghi. Dữ liệu không hợp lệ thì giữ nguyên bản đang chạy.

$ErrorActionPreference = "Stop"
$base = "https://quyennguyen2989-ui.github.io/thutuc-assistant/data"
$dest = "C:\tchc\site\data"
$archiveRoot = "C:\tchc\archive"
$logFile = "C:\tchc\logs\sync.log"
$names = @("meta.json", "van_ban.json", "tthc.json", "thay_doi.json")

function Write-Log([string]$message) {
  New-Item -ItemType Directory -Path (Split-Path $logFile) -Force | Out-Null
  Add-Content -Path $logFile -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message)
}

function Get-Hash([string]$path) {
  if (-not (Test-Path $path)) { return "" }
  return (Get-FileHash -Path $path -Algorithm SHA256).Hash
}

$staging = Join-Path $env:TEMP ("tchc-sync-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $staging | Out-Null

try {
  foreach ($name in $names) {
    Invoke-WebRequest -Uri "$base/$name" -OutFile (Join-Path $staging $name) -UseBasicParsing -TimeoutSec 120
  }

  # Kiểm tra hợp lệ: đúng định dạng JSON và có dữ liệu thật
  $meta = Get-Content (Join-Path $staging "meta.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  $tthc = Get-Content (Join-Path $staging "tthc.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  $vanBan = Get-Content (Join-Path $staging "van_ban.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  $null = Get-Content (Join-Path $staging "thay_doi.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  if (@($tthc).Count -lt 20 -or @($vanBan).Count -lt 20) {
    throw "du lieu tai ve qua it (thu tuc $(@($tthc).Count), van ban $(@($vanBan).Count)), giu nguyen ban cu"
  }

  $changed = @($names | Where-Object { (Get-Hash (Join-Path $staging $_)) -ne (Get-Hash (Join-Path $dest $_)) })
  if ($changed.Count -eq 0) {
    Write-Log "khong co thay doi (kiem tra luc $($meta.cap_nhat_luc))"
    return
  }

  New-Item -ItemType Directory -Path $dest -Force | Out-Null
  $backup = Join-Path $archiveRoot (Get-Date -Format "yyyyMMdd-HHmmss")
  New-Item -ItemType Directory -Path $backup -Force | Out-Null
  foreach ($name in $names) {
    if (Test-Path (Join-Path $dest $name)) { Copy-Item (Join-Path $dest $name) $backup }
  }
  foreach ($name in $changed) {
    Move-Item -Path (Join-Path $staging $name) -Destination (Join-Path $dest $name) -Force
  }
  Write-Log ("da cap nhat " + ($changed -join ", ") + "; ban cu luu tai $backup; kiem tra luc $($meta.cap_nhat_luc)")
}
catch {
  Write-Log ("loi: " + $_.Exception.Message)
  exit 1
}
finally {
  Remove-Item -Path $staging -Recurse -Force -ErrorAction SilentlyContinue
}
