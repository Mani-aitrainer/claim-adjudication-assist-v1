<#
.SYNOPSIS
    Installs Terraform on Windows for the current user (no admin rights needed).

.DESCRIPTION
    Downloads the official HashiCorp release zip, verifies its SHA256 checksum,
    extracts terraform.exe into the install directory and adds that directory
    to the user PATH.

.PARAMETER Version
    Terraform version to install (e.g. 1.16.3). Defaults to the latest release.

.PARAMETER InstallDir
    Where terraform.exe is placed. Defaults to %LOCALAPPDATA%\Programs\terraform.

.EXAMPLE
    .\scripts\install_terraform.ps1
    .\scripts\install_terraform.ps1 -Version 1.9.8
#>
[CmdletBinding()]
param(
    [string]$Version,
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\terraform')
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # makes Invoke-WebRequest much faster
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$arch = if ([Environment]::Is64BitOperatingSystem) {
    if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }
} else { '386' }

if (-not $Version) {
    Write-Host 'Looking up latest Terraform version...'
    $Version = (Invoke-RestMethod 'https://checkpoint-api.hashicorp.com/v1/check/terraform').current_version
}
$Version = $Version.TrimStart('v')

$exe = Join-Path $InstallDir 'terraform.exe'
if (Test-Path $exe) {
    $current = (& $exe version -json | ConvertFrom-Json).terraform_version
    if ($current -eq $Version) {
        Write-Host "Terraform $Version is already installed at $exe"
        return
    }
    Write-Host "Upgrading Terraform $current -> $Version"
}

$baseUrl  = "https://releases.hashicorp.com/terraform/$Version"
$zipName  = "terraform_${Version}_windows_${arch}.zip"
$zipPath  = Join-Path $env:TEMP $zipName

try {
    Write-Host "Downloading $zipName..."
    Invoke-WebRequest "$baseUrl/$zipName" -OutFile $zipPath -UseBasicParsing

    Write-Host 'Verifying checksum...'
    $sums = (Invoke-WebRequest "$baseUrl/terraform_${Version}_SHA256SUMS" -UseBasicParsing).Content
    if ($sums -is [byte[]]) { $sums = [Text.Encoding]::UTF8.GetString($sums) }
    $line = $sums -split "`n" | Where-Object { $_ -match [regex]::Escape($zipName) }
    if (-not $line) { throw "No checksum found for $zipName" }
    $expected = ($line -split '\s+')[0].ToLower()
    $actual   = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLower()
    if ($expected -ne $actual) { throw "Checksum mismatch (expected $expected, got $actual)" }

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Expand-Archive $zipPath -DestinationPath $InstallDir -Force
}
finally {
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
}

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (($userPath -split ';') -notcontains $InstallDir) {
    [Environment]::SetEnvironmentVariable('Path', (($userPath.TrimEnd(';'), $InstallDir) -join ';').TrimStart(';'), 'User')
    Write-Host "Added $InstallDir to user PATH (restart your terminal to pick it up)"
}
# Make it usable in the current session too
if (($env:Path -split ';') -notcontains $InstallDir) { $env:Path += ";$InstallDir" }

& $exe version
