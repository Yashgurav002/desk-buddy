# Builds the Windows release: release\DeskBuddy\ (DeskBuddy.exe + dbhook.exe, one shared folder)
# and release\DeskBuddy-v2.0.0-windows.zip.
# Needs: pip install -r requirements.txt pyinstaller. Run: powershell -ExecutionPolicy Bypass -File build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Version = "2.0.0"
$Out = Join-Path $PSScriptRoot "release"
$App = Join-Path $Out "DeskBuddy"
$Zip = Join-Path $Out "DeskBuddy-v$Version-windows.zip"

function Build($name, $script, $mode) {
    python -m PyInstaller --noconfirm --clean --onedir $mode --name $name `
        --distpath build\dist --workpath build\work --specpath build $script
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for $name" }
}

Build "DeskBuddy" "desk_buddy.pyw" "--windowed"
Build "dbhook" "dbhook.py" "--console"

if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
New-Item -ItemType Directory -Force $Out | Out-Null
Copy-Item -Recurse build\dist\DeskBuddy $App
# dbhook only needs stdlib, a subset of DeskBuddy's runtime: add its exe and any runtime file the panel lacks.
Copy-Item build\dist\dbhook\dbhook.exe $App
Get-ChildItem -Recurse -File build\dist\dbhook\_internal | ForEach-Object {
    $rel = $_.FullName.Substring((Resolve-Path build\dist\dbhook\_internal).Path.Length + 1)
    $dst = Join-Path $App "_internal\$rel"
    if (-not (Test-Path $dst)) {
        New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
        Copy-Item $_.FullName $dst
    }
}
Copy-Item LICENSE $App

Compress-Archive -Path $App -DestinationPath $Zip -Force
Write-Host "Built $App"
Write-Host "Built $Zip"
