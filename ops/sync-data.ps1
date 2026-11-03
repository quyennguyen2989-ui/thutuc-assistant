# Đồng bộ dữ liệu tra cứu từ GitHub Pages về máy chủ.
# Chạy hằng ngày bằng tác vụ đã lên lịch. Chỉ ghi đè khi dữ liệu thật sự thay đổi,
# và luôn sao lưu bản cũ các tệp JSON trước khi ghi. Dữ liệu không hợp lệ thì giữ nguyên bản đang chạy.
# Gồm: dữ liệu thủ tục và văn bản, bộ kiến thức (kien_thuc), và toàn văn (vbpl_text, nguon_text).

$ErrorActionPreference = "Stop"
$base = "https://quyennguyen2989-ui.github.io/thutuc-assistant/data"
$dest = "C:\tchc\site\data"
$archiveRoot = "C:\tchc\archive"
$logFile = "C:\tchc\logs\sync.log"
$jsonNames = @("meta.json", "van_ban.json", "tthc.json", "thay_doi.json", "kien_thuc/tom_tat.json", "vbpl_text/index.json", "nguon_text/index.json")

function Write-Log([string]$message) {
  New-Item -ItemType Directory -Path (Split-Path $logFile) -Force | Out-Null
  Add-Content -Path $logFile -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message)
}

function Get-Hash([string]$path) {
  if (-not (Test-Path $path)) { return "" }
  return (Get-FileHash -Path $path -Algorithm SHA256).Hash
}

function Get-RelativePath([string]$name) {
  return $name -replace "/", "\"
}

$staging = Join-Path $env:TEMP ("tchc-sync-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $staging | Out-Null

try {
  # 1. Tải các tệp JSON (kể cả chỉ mục toàn văn) vào thư mục tạm
  foreach ($name in $jsonNames) {
    $target = Join-Path $staging (Get-RelativePath $name)
    New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
    Invoke-WebRequest -Uri "$base/$name" -OutFile $target -UseBasicParsing -TimeoutSec 120
  }

  # 2. Kiểm tra hợp lệ: đúng định dạng JSON và có dữ liệu thật
  $meta = Get-Content (Join-Path $staging "meta.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  $tthc = Get-Content (Join-Path $staging "tthc.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  $vanBan = Get-Content (Join-Path $staging "van_ban.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  $null = Get-Content (Join-Path $staging "thay_doi.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  $null = Get-Content (Join-Path $staging "kien_thuc\tom_tat.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  if (@($tthc).Count -lt 20 -or @($vanBan).Count -lt 20) {
    throw "du lieu tai ve qua it (thu tuc $(@($tthc).Count), van ban $(@($vanBan).Count)), giu nguyen ban cu"
  }

  # 3. Danh sách tệp toàn văn lấy từ chỉ mục (vbpl_text là từ điển, nguon_text là danh sách)
  $textFiles = @()
  $vbplIndex = Get-Content (Join-Path $staging "vbpl_text\index.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  foreach ($property in $vbplIndex.PSObject.Properties) {
    if ($property.Value.tep) {
      $file = [string]$property.Value.tep
      if (-not $file.EndsWith(".txt")) { $file += ".txt" }
      $textFiles += "vbpl_text/$file"
    }
  }
  $nguonIndex = Get-Content (Join-Path $staging "nguon_text\index.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  foreach ($entry in @($nguonIndex)) {
    if ($entry.tep) { $textFiles += "nguon_text/$([string]$entry.tep)" }
  }
  if ($textFiles.Count -lt 20) {
    throw "chi muc toan van qua it ($($textFiles.Count) tep), giu nguyen ban cu"
  }

  # 4. Tải toàn văn vào thư mục tạm
  foreach ($file in $textFiles) {
    $target = Join-Path $staging (Get-RelativePath $file)
    if (-not (Test-Path $target)) {
      New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
      Invoke-WebRequest -Uri "$base/$file" -OutFile $target -UseBasicParsing -TimeoutSec 120
    }
  }

  # 5. So sánh và ghi các tệp thay đổi
  $allNames = @($jsonNames) + @($textFiles)
  $changed = @($allNames | Where-Object { (Get-Hash (Join-Path $staging (Get-RelativePath $_))) -ne (Get-Hash (Join-Path $dest (Get-RelativePath $_))) })
  if ($changed.Count -eq 0) {
    Write-Log "khong co thay doi (kiem tra luc $($meta.cap_nhat_luc)); van ban $(@($vanBan).Count), toan van $($textFiles.Count)"
    return
  }

  New-Item -ItemType Directory -Path $dest -Force | Out-Null
  $backup = Join-Path $archiveRoot (Get-Date -Format "yyyyMMdd-HHmmss")
  New-Item -ItemType Directory -Path $backup -Force | Out-Null
  foreach ($name in $jsonNames) {
    $current = Join-Path $dest (Get-RelativePath $name)
    if (Test-Path $current) { Copy-Item $current (Join-Path $backup ($name -replace "/", "_")) }
  }
  foreach ($name in $changed) {
    $target = Join-Path $dest (Get-RelativePath $name)
    New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
    Move-Item -Path (Join-Path $staging (Get-RelativePath $name)) -Destination $target -Force
  }
  Write-Log ("da cap nhat " + $changed.Count + " tep (" + (($changed | Select-Object -First 8) -join ", ") + "...); ban cu JSON luu tai $backup; kiem tra luc $($meta.cap_nhat_luc)")
}
catch {
  Write-Log ("loi: " + $_.Exception.Message)
  exit 1
}
finally {
  Remove-Item -Path $staging -Recurse -Force -ErrorAction SilentlyContinue
}
