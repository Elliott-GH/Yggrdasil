param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)
$vdir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = ""
if ($ExtraArgs.Count -eq 0) {
    $candidates = @(
        (Join-Path $vdir ".venv\Scripts\pythonw.exe"),
        "C:\AntiGravityFiles\MasterAgent\.venv\Scripts\pythonw.exe",
        "pythonw"
    )
    $pyw = $candidates | Where-Object { $_ -eq "pythonw" -or (Test-Path $_) } | Select-Object -First 1
    Start-Process -FilePath $pyw -ArgumentList "`"$(Join-Path $vdir 'Yggdrasil.pyw')`""
} else {
    $candidates = @(
        (Join-Path $vdir ".venv\Scripts\python.exe"),
        "C:\AntiGravityFiles\MasterAgent\.venv\Scripts\python.exe",
        "python"
    )
    $py = $candidates | Where-Object { $_ -eq "python" -or (Test-Path $_) } | Select-Object -First 1
    & $py (Join-Path $vdir "app-0.5.0\YggdrasilStudio.pyw") @ExtraArgs
}
