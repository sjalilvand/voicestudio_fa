# Nonpublishing diagnostic: compile a tiny executable and bundle both MSI scopes.
# Uses the actual repository template/renderer and Tauri's generated resources.
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$fixture = Join-Path $env:RUNNER_TEMP 'voicestudio-wix-diagnostic'
$artifacts = Join-Path $repo 'wix-diagnostic-artifacts'
$target = 'x86_64-pc-windows-msvc'
$lock = Get-Content "$repo/bun.lock" -Raw
$cliMatch = [regex]::Match($lock, '"@tauri-apps/cli":\s*\["@tauri-apps/cli@([^"\s]+)"')
if (-not $cliMatch.Success) { throw 'Cannot resolve the Tauri CLI version from bun.lock' }
$cliPackage = '@tauri-apps/cli@' + $cliMatch.Groups[1].Value
New-Item -ItemType Directory -Force -Path $fixture, $artifacts, "$fixture/src", "$fixture/resources/nested", "$fixture/binaries" | Out-Null
@'
[package]
name = "wix-diagnostic"
version = "0.0.0"
edition = "2021"
[workspace]
'@ | Set-Content -Encoding utf8 "$fixture/Cargo.toml"
'fn main() { println!("MSI authoring diagnostic only"); }' | Set-Content -Encoding utf8 "$fixture/src/main.rs"
'Nested resource payload' | Set-Content -Encoding utf8 "$fixture/resources/nested/payload.txt"
'Root resource payload' | Set-Content -Encoding utf8 "$fixture/resources/readme.txt"
Copy-Item "$repo/frontend/src-tauri/wix/main.wxs" "$fixture/system.wxs"
Copy-Item "$repo/frontend/src-tauri/icons/icon.ico" "$fixture/icon.ico"
$config = @{
    productName = 'VoiceStudio MSI Diagnostic'
    version = '0.0.0'
    identifier = 'com.debpalash.voicestudio.wixdiagnostic'
    build = @{}
    bundle = @{
        active = $true
        targets = @('msi')
        createUpdaterArtifacts = $false
        icon = @('icon.ico')
        resources = @('resources/**/*')
        externalBin = @('binaries/helper')
        windows = @{
            webviewInstallMode = @{ type = 'skip' }
            wix = @{ template = 'system.wxs'; enableElevatedUpdateTask = $false }
        }
    }
}
$config | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 "$fixture/tauri.conf.json"
Push-Location $fixture
try {
    & cargo build --release --target $target
    if ($LASTEXITCODE -ne 0) { throw 'Tiny diagnostic executable build failed' }
    Copy-Item "$fixture/target/$target/release/wix-diagnostic.exe" "$fixture/binaries/helper-$target.exe"
    $results = @{}
    foreach ($scope in @('system', 'per-user')) {
        if ($scope -eq 'per-user') {
            & python "$repo/scripts/render-per-user-wix.py" --source "$fixture/system.wxs" --system-wxs "$fixture/target/$target/release/wix/x64/main.wxs" --output "$fixture/per-user.wxs"
            if ($LASTEXITCODE -ne 0) { throw 'Per-user template rendering failed' }
            Remove-Item "$fixture/target/$target/release/wix", "$fixture/target/$target/release/bundle" -Recurse -Force -ErrorAction SilentlyContinue
        }
        $scopeConfig = @{
            productName = "VoiceStudio MSI Diagnostic $scope"
            bundle = @{ windows = @{ wix = @{ template = "$scope.wxs" } } }
        }
        $scopeConfig | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 "$fixture/$scope.conf.json"
        $log = Join-Path $artifacts "$scope.log"
        $ErrorActionPreference = 'Continue'
        & bun x --package $cliPackage tauri bundle -vv --target $target --bundles msi --config "$scope.conf.json" *> $log
        $results[$scope] = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        Get-Content $log
        $capture = Join-Path $artifacts $scope
        New-Item -ItemType Directory -Force -Path $capture | Out-Null
        Get-ChildItem "$fixture/target" -Recurse -File |
            Where-Object { $_.Extension -in @('.wxs', '.wxl', '.wixobj', '.wixpdb', '.msi') } |
            Copy-Item -Destination $capture -Force
    }
    $results | ConvertTo-Json | Set-Content -Encoding utf8 "$artifacts/results.json"
    if ($results.Values | Where-Object { $_ -ne 0 }) {
        throw "MSI authoring failure; inspect wix-diagnostic-artifacts logs and rendered WiX"
    }
} finally {
    Pop-Location
}
