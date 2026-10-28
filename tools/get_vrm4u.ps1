# Download the pinned VRM4U release for UE 5.8, check its SHA-256 and unzip it
# into UnrealProject/Plugins/VRM4U (gitignored).
#
#   powershell -ExecutionPolicy Bypass -File tools\get_vrm4u.ps1
#
# VRM4U is MIT licensed (c) Haruyoshi Yamamoto, https://github.com/ruyo/VRM4U
# To move to a new release, change all three values below together, using the
# "digest" field of the asset on the GitHub release API.
$ErrorActionPreference = "Stop"

$Tag    = "v1.2026.10.17"
$Asset  = "VRM4U_5_8_20261017.zip"
$Sha256 = "4ab9d363c006a00c6bf10712b6b5fb79e4aad3ee859927f4ae0216e96f677f3f"
$Url    = "https://github.com/ruyo/VRM4U/releases/download/$Tag/$Asset"

$Root    = Split-Path -Parent $PSScriptRoot
$Project = Join-Path $Root "UnrealProject"
$Plugin  = Join-Path $Project "Plugins\VRM4U"
$Cache   = Join-Path $Root "data\raw"
$Zip     = Join-Path $Cache $Asset

New-Item -ItemType Directory -Force -Path $Cache | Out-Null

if (-not (Test-Path $Zip)) {
    Write-Host "Downloading $Url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $Url -OutFile "$Zip.part" -UseBasicParsing
    Move-Item -Force "$Zip.part" $Zip
}

$Actual = (Get-FileHash -Algorithm SHA256 -Path $Zip).Hash.ToLowerInvariant()
if ($Actual -ne $Sha256) {
    Remove-Item -Force $Zip
    throw "SHA-256 mismatch for $Asset. Expected $Sha256, got $Actual. The file was deleted; run again."
}
Write-Host "SHA-256 OK: $Actual"

if (Test-Path $Plugin) {
    Write-Host "Removing old $Plugin"
    Remove-Item -Recurse -Force $Plugin
}

# The zip's entries start with Plugins\VRM4U\, so extract into UnrealProject\.
Expand-Archive -Path $Zip -DestinationPath $Project -Force

if (-not (Test-Path (Join-Path $Plugin "VRM4U.uplugin"))) {
    throw "VRM4U.uplugin not found under $Plugin after extract."
}
# Same HK patch as tools/get_vrm4u.py (see the comment there): no Content Browser refresh
# under UnrealEditor-Cmd, where UE 5.8.4 has no Slate application and asserts.
$PatchFile = Join-Path $Plugin "Source\VRM4ULoader\Private\LoaderBPFunctionLibrary.cpp"
$PatchOld  = "if (VRMConverter::IsImportMode()){"
$PatchNew  = "if (VRMConverter::IsImportMode() && !IsRunningCommandlet()){ // HK patch: no Content Browser in commandlets"
$Text = [IO.File]::ReadAllText($PatchFile)
if (-not $Text.Contains($PatchNew)) {
    if (([regex]::Matches($Text, [regex]::Escape($PatchOld))).Count -ne 1) {
        throw "VRM4U patch target not found exactly once in $PatchFile"
    }
    [IO.File]::WriteAllText($PatchFile, $Text.Replace($PatchOld, $PatchNew))
}
Write-Host "Applied HK patch to $PatchFile"
Set-Content -Path (Join-Path $Plugin "HK_VRM4U_VERSION.txt") -Value "$Tag $Asset $Sha256"
Write-Host "VRM4U $Tag installed in $Plugin"
Write-Host "Next: right-click HKFreeRoam.uproject > Generate Visual Studio project files, then build."
