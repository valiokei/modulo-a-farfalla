param([string]$Version = "development")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed ($LASTEXITCODE)" }
}

Invoke-Checked python @("-m", "pip", "install", "-r", "backend/requirements.txt", "pyinstaller==6.16.0")
$previousDesktop = $env:VITE_DESKTOP
$env:VITE_DESKTOP = "true"
Push-Location frontend
try {
    Invoke-Checked npm.cmd @("ci")
    Invoke-Checked npm.cmd @("run", "build")
} finally { Pop-Location; $env:VITE_DESKTOP = $previousDesktop }

Invoke-Checked python @("-m", "pip", "install", "pytest==8.4.2")
$env:PYTHONPATH = "backend"
Invoke-Checked python @("-m", "pytest", "-q", "desktop/test_launcher.py", "desktop/test_update.py", "desktop/test_update_helper.py", "desktop/test_windows_gpu.py", "backend/tests/test_telestration.py")

$archive = Join-Path $env:TEMP "ffmpeg-8.1.2-essentials.zip"
$url = "https://github.com/GyanD/codexffmpeg/releases/download/8.1.2/ffmpeg-8.1.2-essentials_build.zip"
Invoke-WebRequest -Uri $url -OutFile $archive
$expected = "db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec"
if ((Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
    throw "FFmpeg checksum mismatch; refusing to bundle executable"
}
$extract = Join-Path $env:TEMP "modulo-ffmpeg-8.1.2"
Expand-Archive $archive -DestinationPath $extract -Force
$ffmpeg = Get-ChildItem $extract -Filter ffmpeg.exe -Recurse | Select-Object -First 1
if (-not $ffmpeg) { throw "FFmpeg executable missing" }
$vendor = "desktop/vendor/ffmpeg"
New-Item -ItemType Directory $vendor -Force | Out-Null
Copy-Item $ffmpeg.FullName $vendor
Copy-Item (Join-Path $ffmpeg.DirectoryName "ffprobe.exe") $vendor
Get-ChildItem $ffmpeg.Directory.Parent.FullName -File | Copy-Item -Destination $vendor
$encoders = & "$vendor/ffmpeg.exe" -hide_banner -encoders 2>&1 | Out-String
foreach ($encoder in @("h264_nvenc", "h264_qsv", "h264_amf")) {
    if ($encoders -notmatch ("\b" + $encoder + "\b")) { throw "Required GPU encoder missing: $encoder" }
}
Set-Content -Path "desktop/build-version.txt" -Value $Version -NoNewline -Encoding ascii
Invoke-Checked python @("-m", "PyInstaller", "--noconfirm", "--clean", "desktop/modulo-a-farfalla.spec")
Invoke-Checked python @("-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--noconsole", "--name", "ModuloAFarfallaUpdater", "desktop/update_helper.py")
Invoke-Checked python @("desktop/smoke_test.py", "--executable", "dist/ModuloAFarfalla/ModuloAFarfalla.exe")
$compiler = "${env:ProgramFiles(x86)}/Inno Setup 6/ISCC.exe"
if (-not (Test-Path $compiler)) { throw "Install Inno Setup 6 on the build machine" }
Invoke-Checked $compiler @("/DBuildVersion=$Version", "desktop/installer.iss")
Get-ChildItem dist/installer/*.exe | ForEach-Object {
    $hash = (Get-FileHash $_ -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $($_.Name)" | Set-Content ($_.FullName + ".sha256") -Encoding ascii
}
