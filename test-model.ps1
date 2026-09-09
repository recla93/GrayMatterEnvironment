# test-model.ps1 — matrice di verifica per un modello Ollama, da terminale normale (fuori opencode)
# Uso:  .\test-model.ps1 -Model qwenmoe        |   .\test-model.ps1 -Model gemma -SkipThink
param(
    [Parameter(Mandatory=$true)][string]$Model,
    [switch]$SkipThink
)
$ErrorActionPreference = 'Continue'
$base = "http://localhost:11434"

function Ram-Libera { [Math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,1) }
function Chat([hashtable]$body) {
    try {
        $b = $body; $b.model = $Model; $b.stream = $false
        $r = Invoke-RestMethod -Uri "$base/api/chat" -Method Post -Body ($b | ConvertTo-Json -Depth 8) -ContentType "application/json" -TimeoutSec 300
        return @{ ok = $true; r = $r }
    } catch { return @{ ok = $false; err = $_.Exception.Message } }
}

"=== TEST MODELLO: $Model ==="
"RAM libera all'avvio: $(Ram-Libera) GB`n"

# 1. Caricamento + risposta base
$t0 = Get-Date
$r = Chat @{ messages = @(@{role="system"; content="You are helpful."}, @{role="user"; content="Say OK"}); think = (-not $SkipThink) }
if (-not $r.ok) { "FAIL caricamento/base: $($r.err)"; exit 1 }
$loadSec = [Math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
"PASS base (caricato+risposto in ${loadSec}s): '$($r.r.message.content.Trim().Substring(0,[Math]::Min(30,$r.r.message.content.Trim().Length)))'"

if (-not $SkipThink) {
    $th = $r.r.message.thinking
    if ($th) { "PASS thinking separato ($($th.Length) char)" } else { "WARN nessun campo thinking" }
}

# 2. Regressioni: arrangiamenti messaggi che uccidevano il template
$r2 = Chat @{ messages = @(@{role="user"; content="hi"}, @{role="system"; content="Be helpful."}, @{role="user"; content="Say OK"}) }
if ($r2.ok) { "PASS user-prima-di-system (guardia neutralizzata)" } else { "FAIL user-prima-di-system: $($r2.err)" }

$r3 = Chat @{ messages = @(@{role="system"; content="A."}, @{role="system"; content="B."}, @{role="user"; content="Say OK"}) }
if ($r3.ok) { "PASS doppio-system" } else { "FAIL doppio-system: $($r3.err)" }

# 3. Velocita: generazione un po' piu lunga, modello ormai caldo
$t1 = Get-Date
$r4 = Chat @{ messages = @(@{role="user"; content="Write exactly 3 short sentences about the sea."}); think = $false }
if ($r4.ok) {
    $sec = ((Get-Date) - $t1).TotalSeconds
    $tps = [Math]::Round($r4.r.eval_count / ($r4.r.eval_duration/1e9), 1)
    "VELOCITA: $tps tok/s ($($r4.r.eval_count) tok in $([Math]::Round($sec,1))s wall)"
} else { "WARN velocita non misurata: $($r4.err)" }

# 4. Unload + RAM finale
$null = Invoke-RestMethod -Uri "$base/api/generate" -Method Post -Body (@{model=$Model; keep_alive=0} | ConvertTo-Json) -TimeoutSec 20
Start-Sleep 5
"`nRAM libera a fine test: $(Ram-Libera) GB"
"=== FINE ==="
