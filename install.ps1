# SEND — instalador para Windows (PowerShell 5.1+)
#
# Uso (cole no PowerShell):
#   irm https://github.com/contasuportedis-png/SEND/releases/latest/download/install.ps1 | iex
#
# Instala em %USERPROFILE%\.send\send.py e cria o comando `send`
# (arquivo send.cmd, funciona no PowerShell e no Prompt de Comando).

$ErrorActionPreference = "Stop"

Write-Host "⚡ SEND - instalador (Windows)" -ForegroundColor Cyan

# 1) Python 3 é obrigatório
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host "✗ Python 3 não encontrado." -ForegroundColor Red
    Write-Host "  Instale pelo site https://www.python.org/downloads/ (marque 'Add to PATH')"
    exit 1
}

# 2) Destino
$Dest = Join-Path $HOME ".send"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$SendPy  = Join-Path $Dest "send.py"
$SendCmd = Join-Path $Dest "send.cmd"

# 3) Download (release oficial com fallback para o repositório)
$url  = "https://github.com/contasuportedis-png/SEND/releases/latest/download/send.py"
$fallback = "https://github.com/contasuportedis-png/SEND/raw/main/send.py"
Write-Host "⬇ Baixando SEND..."
try {
    Invoke-WebRequest -Uri $url -OutFile $SendPy -UseBasicParsing
} catch {
    Write-Host "  (usando fallback do repositório)"
    Invoke-WebRequest -Uri $fallback -OutFile $SendPy -UseBasicParsing
}

# 4) Launcher `send.cmd` para chamar o Python
@"
@echo off
python "%USERPROFILE%\.send\send.py" %*
"@ | Set-Content -Path $SendCmd -Encoding ASCII

Write-Host "✅ SEND instalado em: $SendPy" -ForegroundColor Green

# 5) Adiciona ao PATH do usuário
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$Dest*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$Dest", "User")
    Write-Host "⚠ .send adicionado ao PATH do usuário. Abra um NOVO terminal para usar o comando 'send'."
} else {
    Write-Host "PATH já configurado."
}

Write-Host ""
Write-Host "Próximos passos:"
Write-Host "  1. Abra o LM Studio -> carregue um modelo -> aba 'Developer' -> Start Server (porta 1234)"
Write-Host "  2. Verifique a conexão:  send --doctor"
Write-Host "  3. Comece a usar:        send"
Write-Host ""
