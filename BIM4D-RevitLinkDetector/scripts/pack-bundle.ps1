#Requires -Version 5.1
<#
.SYNOPSIS
    Builds RevitLinkDetector for ONE supported Revit year and lays it out
    as that year's Design Automation AppBundle zip.

.DESCRIPTION
    RevitLinkDetector supports Revit 2024-2027, which span three different
    .NET runtimes (net48, net8.0-windows, net10.0-windows - see the
    project .csproj and scripts/revit-versions.json for exactly which year
    maps to which). An AppBundle is bound to exactly one Design Automation
    engine, so each Revit year gets its own AppBundle + Activity, and this
    script builds/packages one year at a time rather than all of them.

    Run this from Visual Studio's Developer PowerShell, or any PowerShell
    with `dotnet` on PATH, on the Windows machine that has the matching
    Revit version (or the Design Automation SDK) installed - this project
    cannot be built from the cloud dev session that authored these files
    (no dotnet/msbuild/Revit there).

    Steps:
      1. Looks up -RevitYear in scripts/revit-versions.json for its target
         framework, engine id, and any open caveats (printed as a warning).
      2. dotnet build -c Release_<year> (x64) - RevitLinkDetector.csproj's
         named per-year configurations (Debug_2024/Release_2024, etc. -
         see RevitLinkDetector.sln) narrow TargetFrameworks down to exactly
         that year's one framework, so no separate -f flag is needed and
         there's no ambiguity about which framework got built.
      3. Copies the built DLL + Newtonsoft.Json.dll + RevitLinkDetector.addin
         from bin\x64\Release_<year>\<tfm>\ into
         bundle/RevitLinkDetector<year>.bundle/Contents/.
      4. Zips bundle/RevitLinkDetector<year>.bundle/ into
         bundle/RevitLinkDetector<year>.bundle.zip - the file
         appbundle-register.js uploads to APS for that year.

.PARAMETER RevitYear
    Which supported year to build: 2024, 2025, 2026, or 2027.

.PARAMETER UseLocalRevitInstall
    By default RevitLinkDetector.csproj builds against NuGet reference
    packages (Nice3point.Revit.Api.RevitAPI + Autodesk.Forge.DesignAutomation.Revit)
    and needs no local Revit install at all. Pass this switch to instead
    build against an actual local Revit install's RevitAPI.dll /
    DesignAutomationFramework.dll (implied automatically if you pass
    -RevitApiDir below).

.PARAMETER RevitApiDir
    Folder containing RevitAPI.dll / DesignAutomationFramework.dll for
    that year, for a local-install build. Defaults to that target
    framework's default in the .csproj (a standard
    "C:\Program Files\Autodesk\Revit <year>" path); pass this if that
    Revit year is installed elsewhere. Passing this implies
    -UseLocalRevitInstall.

.EXAMPLE
    .\scripts\pack-bundle.ps1 -RevitYear 2024
.EXAMPLE
    .\scripts\pack-bundle.ps1 -RevitYear 2026 -RevitApiDir "D:\Autodesk\Revit 2026"
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(2024, 2025, 2026, 2027)]
    [int]$RevitYear,

    [switch]$UseLocalRevitInstall,

    [string]$RevitApiDir
)

$ErrorActionPreference = "Stop"

$RepoRoot     = Split-Path -Parent $PSScriptRoot
$ProjectPath  = Join-Path $RepoRoot "src\RevitLinkDetector\RevitLinkDetector.csproj"
$VersionsPath = Join-Path $PSScriptRoot "revit-versions.json"

$versions = Get-Content $VersionsPath -Raw | ConvertFrom-Json
$versionEntry = $versions | Where-Object { $_.year -eq $RevitYear }
if (-not $versionEntry) {
    throw "No entry for Revit $RevitYear in $VersionsPath."
}
$tfm = $versionEntry.tfm

if ($versionEntry.status -and $versionEntry.status -ne "stable") {
    Write-Host "NOTE (Revit $RevitYear, status=$($versionEntry.status)): $($versionEntry.note)" -ForegroundColor Yellow
}

$BundleName  = "RevitLinkDetector$RevitYear"
$BundleRoot  = Join-Path $RepoRoot "bundle\$BundleName.bundle"
$ContentsDir = Join-Path $BundleRoot "Contents"
$ZipPath     = Join-Path $RepoRoot "bundle\$BundleName.bundle.zip"

# Named per-year configuration (see RevitLinkDetector.sln /
# RevitLinkDetector.csproj) - this alone narrows TargetFrameworks to $tfm,
# so no -f flag is passed here (passing both -c and -f is redundant at
# best and risks the two disagreeing if revit-versions.json and the
# .csproj's own per-Configuration mapping ever drift apart).
$Configuration = "Release_$RevitYear"

$buildArgs = @($ProjectPath, "-c", $Configuration, "-p:Platform=x64")
# Passing -RevitApiDir implies you have that year's Revit installed there
# and want to build against it, not the default NuGet packages.
if ($RevitApiDir -and -not $UseLocalRevitInstall) { $UseLocalRevitInstall = $true }
if ($UseLocalRevitInstall) { $buildArgs += "-p:UseLocalRevitInstall=true" }
if ($RevitApiDir) { $buildArgs += "-p:RevitApiDir=$RevitApiDir" }

Write-Host "==> Building RevitLinkDetector for Revit $RevitYear (configuration $Configuration, framework $tfm, engine $($versionEntry.engine))" -ForegroundColor Cyan
dotnet build @buildArgs
if ($LASTEXITCODE -ne 0) { throw "dotnet build failed with exit code $LASTEXITCODE." }

# SDK-style output path with <Platforms>x64</Platforms> set inserts the
# platform ahead of the configuration: bin\x64\<Configuration>\<TFM>\ -
# verified against a real build's actual output path, not assumed.
$OutDir        = Join-Path $RepoRoot "src\RevitLinkDetector\bin\x64\$Configuration\$tfm"
$BuiltDll      = Join-Path $OutDir "RevitLinkDetector.dll"
$NewtonsoftDll = Join-Path $OutDir "Newtonsoft.Json.dll"

foreach ($f in @($BuiltDll, $NewtonsoftDll)) {
    if (-not (Test-Path $f)) { throw "Expected build output not found: $f (did the build actually target $tfm?)" }
}

Write-Host "==> Laying out bundle at $ContentsDir" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $ContentsDir | Out-Null

Copy-Item $BuiltDll      $ContentsDir -Force
Copy-Item $NewtonsoftDll $ContentsDir -Force
Copy-Item (Join-Path $RepoRoot "src\RevitLinkDetector\RevitLinkDetector.addin") $ContentsDir -Force

$PackageContentsPath = Join-Path $BundleRoot "PackageContents.xml"
if (-not (Test-Path $PackageContentsPath)) {
    throw "PackageContents.xml not found at $PackageContentsPath. Expected one checked in per year under bundle\$BundleName.bundle\ already - see docs/BUILD.md."
}

Write-Host "==> Zipping $BundleRoot -> $ZipPath" -ForegroundColor Cyan
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

# Compress-Archive zips the FOLDER itself as the top-level entry; APS's
# AppBundle upload expects RevitLinkDetector<year>.bundle/ to be the zip's
# root, so we zip the bundle folder's *contents* by globbing, not the
# folder reference itself, to avoid an extra nesting level.
$ItemsToZip = Get-ChildItem -Path $BundleRoot
Compress-Archive -Path $ItemsToZip.FullName -DestinationPath $ZipPath -Force

Write-Host "==> Done: $ZipPath" -ForegroundColor Green
Write-Host "Next: node scripts\appbundle-register.js --year $RevitYear (review it first - it creates/updates real APS resources)." -ForegroundColor Yellow
