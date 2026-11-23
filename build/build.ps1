# Got It! - monta o aplicativo e o instalador no Windows.
# Rode pelo GERAR_INSTALADOR.bat (duplo clique). Precisa de internet só nesta etapa.
#
#   1. instala o "uv" (gerenciador de Python), se ainda não houver;
#   2. cria um ambiente Python 3.12 isolado na pasta .venv (não mexe no resto do PC);
#   3. empacota o aplicativo com o PyInstaller e confere o pacote;
#   4. instala o Inno Setup, se preciso, e gera o instalador em dist\.

param([switch]$CI)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host ""; Write-Host "ERRO: $text" -ForegroundColor Red; exit 1 }

Step "Verificando o uv (gerenciador de Python)"
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) { Fail "Não foi possível instalar o uv. Feche esta janela, abra de novo e tente outra vez." }
}
Write-Host (& uv --version)

Step "Preparando o ambiente Python 3.12"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & uv venv .venv --python 3.12
    if ($LASTEXITCODE -ne 0) { Fail "Falha ao criar o ambiente Python." }
}
& uv pip install --python .venv\Scripts\python.exe -r build\requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "Falha ao instalar as bibliotecas." }
$Py = Join-Path $Root ".venv\Scripts\python.exe"

Step "Empacotando o aplicativo"
& $Py -m PyInstaller build\GotIt.spec --noconfirm --clean --distpath dist --workpath build\work
if ($LASTEXITCODE -ne 0) { Fail "Falha no PyInstaller." }

Step "Conferindo o pacote"
$report = Join-Path $env:TEMP "gotit_selftest.json"
Remove-Item $report -ErrorAction SilentlyContinue
$p = Start-Process -FilePath "dist\GotIt\GotIt.exe" -ArgumentList "--self-test", "`"$report`"" -Wait -PassThru
if (Test-Path $report) { Get-Content $report | Write-Host }
if ($p.ExitCode -ne 0) { Fail "O pacote não passou na conferência (veja acima)." }

Step "Gerando o instalador"
function Find-ISCC {
    $cands = @(
        "$env:ProgramFiles\Inno Setup 7\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $cands) { if (Test-Path $c) { return $c } }
    return $null
}
$iscc = Find-ISCC
if (-not $iscc) {
    if ($CI) { choco install innosetup -y --no-progress | Out-Null; $iscc = Find-ISCC }
    if (-not $iscc) {
        winget install --id JRSoftware.InnoSetup -e -s winget --silent --accept-package-agreements --accept-source-agreements
        $iscc = Find-ISCC
    }
    if (-not $iscc) { Fail "Instale o Inno Setup (jrsoftware.org/isdl.php) e rode este script de novo." }
}
& $iscc "build\GotIt.iss"
if ($LASTEXITCODE -ne 0) { Fail "Falha ao gerar o instalador." }

$out = Get-ChildItem "dist\GotIt_Setup_*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host ""
Write-Host "PRONTO! Instalador gerado:" -ForegroundColor Green
Write-Host "  $($out.FullName)" -ForegroundColor Green
if (-not $CI) { explorer.exe "/select,`"$($out.FullName)`"" }
