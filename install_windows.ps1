# Leo 3D AI Cartoon Studio - Windows 10/11 installer (run in PowerShell from the project folder):
#   powershell -ExecutionPolicy Bypass -File install_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$BlenderVersion = "4.5.15"
$BlenderZip = "blender-$BlenderVersion-windows-x64.zip"
$BlenderSha256 = "52dd02fd74877fa08e74b67d7854cf32468a232c02aaa19b6844c91285574f8d"

Write-Host "== 1/4 Python ==" -ForegroundColor Cyan
$py = $null
foreach ($v in @("3.12", "3.11")) {
    try { & py -$v --version *> $null; if ($LASTEXITCODE -eq 0) { $py = "py -$v"; break } } catch {}
}
if (-not $py) {
    Write-Host "Python 3.11 or 3.12 not found. Install it from https://www.python.org/downloads/windows/" -ForegroundColor Red
    Write-Host "(tick 'Add python.exe to PATH' and keep the default 'tcl/tk' option), then run this script again."
    exit 1
}
Write-Host "Using $py"

Write-Host "== 2/4 Virtual environment and packages ==" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) { Invoke-Expression "$py -m venv .venv" }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { Write-Host "pip install failed" -ForegroundColor Red; exit 1 }

Write-Host "== 3/4 Blender $BlenderVersion LTS (portable, ~400 MB) ==" -ForegroundColor Cyan
$existing = Get-ChildItem -Path "tools" -Filter "blender.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$installed = Get-ChildItem -Path "$env:ProgramFiles\Blender Foundation" -Filter "blender.exe" -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match "Blender 4\." } | Select-Object -First 1
if ($existing -or $installed) {
    Write-Host "Blender already available."
} else {
    New-Item -ItemType Directory -Force -Path "tools" | Out-Null
    $zipPath = Join-Path "tools" $BlenderZip
    Write-Host "Downloading $BlenderZip from download.blender.org ..."
    Invoke-WebRequest -Uri "https://download.blender.org/release/Blender4.5/$BlenderZip" -OutFile $zipPath
    $hash = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLower()
    if ($hash -ne $BlenderSha256) { Write-Host "Checksum mismatch for $BlenderZip" -ForegroundColor Red; exit 1 }
    Expand-Archive -Path $zipPath -DestinationPath "tools" -Force
    Remove-Item $zipPath
}

Write-Host "== Start Menu and Desktop shortcuts ==" -ForegroundColor Cyan
$shell = New-Object -ComObject WScript.Shell
$targets = @("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Leo 3D AI Cartoon Studio.lnk",
             "$([Environment]::GetFolderPath('Desktop'))\Leo 3D AI Cartoon Studio.lnk")
foreach ($lnk in $targets) {
    $sc = $shell.CreateShortcut($lnk)
    $sc.TargetPath = (Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe")
    $sc.Arguments = "`"$(Join-Path $PSScriptRoot 'main.py')`""
    $sc.WorkingDirectory = $PSScriptRoot
    $sc.IconLocation = (Join-Path $PSScriptRoot "assets\icon.ico")
    $sc.Description = "Paste an Urdu or English script and get a 3D animated cartoon video"
    $sc.Save()
}

Write-Host "== 4/4 Checking the installation ==" -ForegroundColor Cyan
& .\.venv\Scripts\python.exe main.py --check
Write-Host ""
Write-Host "Done. Start the studio with: run_windows.bat" -ForegroundColor Green
Write-Host "FFmpeg comes with the imageio-ffmpeg package; Urdu fonts are bundled in assets\fonts."
