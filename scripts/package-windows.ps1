<#
.SYNOPSIS
  Build the v2 desktop app (Go + Wails) and produce a portable zip.

.DESCRIPTION
  Pipeline: build frontend -> sync to core/ui/dist -> go test -> build exe ->
  optional signing -> zip. The legacy Python pipeline (BuildPackage.py) is untouched.

  NOTE: this file is intentionally ASCII-only. Windows PowerShell 5.1 reads .ps1
  as ANSI when there is no BOM, which corrupts non-ASCII string literals.

.EXAMPLE
  powershell -File scripts\package-windows.ps1 -Version 2.0.0
#>
param(
  [string]$Version = "2.0.0",
  [string]$Arch = "amd64",
  [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root "dist"
$commit = (git -C $root rev-parse --short HEAD) 2>$null
if (-not $commit) { $commit = "unknown" }

function Assert-LastExit([string]$Step) {
  if ($LASTEXITCODE -ne 0) {
    throw "$Step failed with exit code $LASTEXITCODE"
  }
}

Write-Host "==> Building frontend" -ForegroundColor Cyan
Push-Location $root
npm ci --include=dev
Assert-LastExit "npm ci"
npm run build -w @tpmsc/web
Assert-LastExit "web build"
node scripts/prepare-ui.mjs
Assert-LastExit "prepare-ui"

if (-not $SkipTests) {
  Write-Host "==> Running Go tests" -ForegroundColor Cyan
  Push-Location (Join-Path $root "core")
  go test ./...
  Assert-LastExit "go test"
  Pop-Location
}

Write-Host "==> Building desktop ($Version / $commit / $Arch)" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $dist | Out-Null
Push-Location (Join-Path $root "desktop\wails")
$env:CGO_ENABLED = "0"
$env:GOARCH = $Arch
$exe = Join-Path $dist "TPMSmartCard-windows-$Arch.exe"
go build -tags desktop -trimpath `
  -ldflags "-s -w -H windowsgui -X main.Version=$Version -X main.Commit=$commit" `
  -o $exe .
Assert-LastExit "go build"
Pop-Location

if ($env:TPMSC_SIGN_TOOL) {
  Write-Host "==> Signing" -ForegroundColor Cyan
  & $env:TPMSC_SIGN_TOOL $exe
} else {
  Write-Host "!! TPMSC_SIGN_TOOL not set: skipping signature" -ForegroundColor Yellow
}

Write-Host "==> Creating zip" -ForegroundColor Cyan
$stage = Join-Path $dist "TPMSmartCard-$Version-windows-$Arch"
if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Copy-Item $exe $stage
Copy-Item (Join-Path $root "README.md") $stage
Copy-Item (Join-Path $root "LICENSE") $stage
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath "$stage.zip" -Force

Pop-Location
Write-Host "==> Done: $stage.zip" -ForegroundColor Green
