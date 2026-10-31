$desktop = [Environment]::GetFolderPath('Desktop')
$ws = New-Object -ComObject WScript.Shell
$shortcutPath = Join-Path $desktop "TikTok Auto Unrepost.lnk"
$s = $ws.CreateShortcut($shortcutPath)
$s.TargetPath = Join-Path $PSScriptRoot "run_app.bat"
$s.WorkingDirectory = $PSScriptRoot
$s.Description = "TikTok Auto Unrepost Desktop App"
$s.Save()
if (Test-Path $shortcutPath) {
    Write-Host "[OK] Acceso directo creado exitosamente en tu Escritorio:"
    Write-Host "     $shortcutPath"
} else {
    Write-Host "[!] Error al guardar el acceso directo."
}
