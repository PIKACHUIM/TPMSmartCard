<#
.SYNOPSIS
  Copy release assets from one GitHub release to another (server-side copy is not supported by GitHub).

.DESCRIPTION
  Downloads the assets of a source release (default: beta) and uploads them to the
  target release id. Large files are streamed with curl progress output.

.PARAMETER ReleaseId
  Numeric id of the target release (not the tag name).

.PARAMETER Filter
  Optional substring filter on asset names, e.g. "cxfree".

.PARAMETER Tag
  Source release tag, default "beta".

.EXAMPLE
  $env:GH_TOKEN = "..."
  powershell -File scripts\publish-release-assets.ps1 -ReleaseId 442623224 -Filter cxfree
#>
param(
  [Parameter(Mandatory = $true)][string]$ReleaseId,
  [string]$Filter = "",
  [string]$Tag = "beta"
)

$ErrorActionPreference = "Stop"
$token = $env:GH_TOKEN
if (-not $token) { throw "GH_TOKEN is required" }

$repo = "PIKACHUIM/TPMSmartCard"
$dir = Join-Path $PSScriptRoot "..\tmp\release-assets"
New-Item -ItemType Directory -Force -Path $dir | Out-Null

$json = curl.exe -k -sS -H "Authorization: Bearer $token" -H "User-Agent: tpmsc-build" `
  "https://api.github.com/repos/$repo/releases/tags/$Tag"
$source = $json | ConvertFrom-Json
if (-not $source.assets) { throw "source release '$Tag' has no assets" }

$assets = $source.assets | Where-Object { $_.name -like "*$Filter*" }
foreach ($asset in $assets) {
  $dest = Join-Path $dir $asset.name
  Write-Host "==> download $($asset.name) ($([math]::Round($asset.size / 1MB, 1)) MiB)"
  if ((-not (Test-Path $dest)) -or ((Get-Item $dest).Length -ne $asset.size)) {
    curl.exe -k -L --progress-bar -o $dest $asset.browser_download_url
    if ($LASTEXITCODE -ne 0) { throw "download failed: $($asset.name)" }
  } else {
    Write-Host "    cached"
  }

  Write-Host "==> upload $($asset.name)"
  $resp = curl.exe -k -sS --progress-bar -X POST `
    -H "Authorization: Bearer $token" -H "User-Agent: tpmsc-build" `
    -H "Content-Type: application/octet-stream" `
    --data-binary "@$dest" `
    "https://uploads.github.com/repos/$repo/releases/$ReleaseId/assets?name=$($asset.name)"
  $obj = $resp | ConvertFrom-Json
  if ($obj.state -ne "uploaded") { throw "upload failed: $($obj.message)" }
  Write-Host "    uploaded id=$($obj.id)"
  Remove-Item $dest -Force
}
