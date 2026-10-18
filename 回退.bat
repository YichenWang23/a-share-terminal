@echo off
setlocal EnableExtensions
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$bak=(Get-Content '_backup\LATEST.txt' -Encoding UTF8).Trim();" ^
  "if(-not (Test-Path $bak)){ Write-Host 'no backup found'; exit 1 };" ^
  "Write-Host ('restoring from ' + $bak);" ^
  "Get-ChildItem $bak -Recurse -File | Where-Object { $_.Name -ne 'MANIFEST.sha256' } | ForEach-Object {" ^
  "  $rel=$_.FullName.Substring($bak.Length+1);" ^
  "  $dst=Join-Path (Get-Location) $rel;" ^
  "  New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null;" ^
  "  Copy-Item -LiteralPath $_.FullName -Destination $dst -Force };" ^
  "Write-Host 'done. restart the app to see the restored version.'"
echo.
pause
exit /b 0
