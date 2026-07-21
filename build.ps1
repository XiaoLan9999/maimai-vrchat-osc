param(
    [Parameter(Mandatory = $true)]
    [string]$GamePackage,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$csc = "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
$assemblyCSharp = Join-Path $GamePackage "Sinmai_Data\Managed\Assembly-CSharp.dll"
$melonLoader = Join-Path $GamePackage "MelonLoader\net35\MelonLoader.dll"
$harmony = Join-Path $GamePackage "MelonLoader\net35\0Harmony.dll"
$versionInfo = Get-Content -LiteralPath (Join-Path $root "app\version.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$appVersion = [string]$versionInfo.app_version
$bridgeVersion = [string]$versionInfo.bridge_version
$dist = [IO.Path]::GetFullPath((Join-Path $root "dist"))
$stage = Join-Path $dist "standalone-stage"
$payload = Join-Path $stage "payload"
$pyWork = Join-Path $dist "pyinstaller-work"
$pySpec = Join-Path $dist "pyinstaller-spec"
$bridgeDll = Join-Path $payload "XiaoLanMaiBrdge.dll"

if (-not $dist.StartsWith(([IO.Path]::GetFullPath($root) + [IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use a dist path outside the project: $dist"
}
foreach ($path in @($csc, $assemblyCSharp, $melonLoader, $harmony)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required file not found: $path" }
}
if (Test-Path -LiteralPath $dist) { Remove-Item -LiteralPath $dist -Recurse -Force }
New-Item -ItemType Directory -Force -Path $payload, $pyWork, $pySpec | Out-Null

& $csc /nologo /target:library /optimize+ /warn:4 `
    /out:$bridgeDll `
    /reference:$melonLoader `
    /reference:$harmony `
    /reference:$assemblyCSharp `
    (Join-Path $root "bridge\XiaoLanMaiBrdge.cs")
if ($LASTEXITCODE -ne 0) { throw "C# compilation failed" }

Copy-Item -LiteralPath (Join-Path $root "bridge\XiaoLanMaiBrdge.ini") -Destination $payload
$bridgeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $bridgeDll).Hash.ToLowerInvariant()
$descriptor = [ordered]@{
    plugin_version = $appVersion
    bridge_version = $bridgeVersion
    sha256 = $bridgeHash
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText(
    (Join-Path $payload "bridge.json"),
    (($descriptor | ConvertTo-Json) + "`n"),
    $utf8NoBom
)

$buildDeps = Join-Path $root ".builddeps"
$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = if ($oldPythonPath) { "$buildDeps;$oldPythonPath" } else { $buildDeps }
try {
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name MaimaiVrchatOsc `
        --distpath $stage `
        --workpath $pyWork `
        --specpath $pySpec `
        --add-data "${payload};payload" `
        (Join-Path $root "app\main.py")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
}
finally {
    $env:PYTHONPATH = $oldPythonPath
}

Copy-Item -LiteralPath (Join-Path $root "README.md") -Destination $stage
Copy-Item -LiteralPath (Join-Path $root "README.zh-CN.md") -Destination $stage
Copy-Item -LiteralPath (Join-Path $root "LICENSE") -Destination $stage
Copy-Item -LiteralPath (Join-Path $root "config.example.json") -Destination $stage
$zip = Join-Path $dist "maimai-vrchat-osc-$appVersion-win64.zip"
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip

Write-Output "Built: $(Join-Path $stage 'MaimaiVrchatOsc.exe')"
Write-Output "Built: $zip"
Write-Output "Bridge: $bridgeVersion sha256=$bridgeHash"
