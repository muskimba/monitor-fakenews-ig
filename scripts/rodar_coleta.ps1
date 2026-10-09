# Chamado pelo Agendador de Tarefas do Windows. Roda a coleta e grava log mensal em logs\.
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
New-Item -ItemType Directory -Force -Path "$raiz\logs" | Out-Null
$log = "$raiz\logs\coleta-$(Get-Date -Format 'yyyy-MM').log"
$env:PYTHONIOENCODING = "utf-8"
& "$raiz\.venv\Scripts\python.exe" -m monitor coletar *>> $log
exit $LASTEXITCODE
