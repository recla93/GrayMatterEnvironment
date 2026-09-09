param([Parameter(Mandatory=$true)][string]$ModelName)
$ErrorActionPreference = 'Stop'

# --- risoluzione manifest ---
$rel = $ModelName.Replace(':', '\')
if ($rel -notmatch '^hf\.co') { $rel = "registry.ollama.ai\library\$rel" }
if ((Get-Item "$env:USERPROFILE\.ollama\models\manifests\$rel").PSIsContainer) { $rel += '\latest' }
$mPath = "$env:USERPROFILE\.ollama\models\manifests\$rel"
$m = Get-Content $mPath | ConvertFrom-Json
$modelLayer = $m.layers | Where-Object { $_.mediaType -match '\.image\.model' }
$blob = "$env:USERPROFILE\.ollama\models\blobs\" + $modelLayer.digest.Replace(':','-')
"Blob: $(Split-Path $blob -Leaf)"

# --- lettura primi 64 MB ---
$fs = [System.IO.File]::OpenRead($blob); $buf = New-Object byte[] (64MB)
$r = $fs.Read($buf, 0, $buf.Length); $fs.Close()
$text = [System.Text.Encoding]::ASCII.GetString($buf, 0, $r)

# --- cerca TUTTE le raise_exception nel template ---
$pattern = '\{\{- raise_exception\([^)]+\) \}\}'
$allMatches = [regex]::Matches($text, $pattern)
if ($allMatches.Count -eq 0) { "Nessuna guardia raise_exception trovata — gia patchato."; exit 0 }
"Trovate $($allMatches.Count) guardie da neutralizzare"

# --- calcola replacement per ogni match (stessa lunghezza byte) ---
$replacements = @()
foreach ($m2 in $allMatches) {
    $off = $m2.Index; $len = $m2.Length
    $base = "{%- if false %}{%- endif %}"
    $fillerLen = $len - $base.Length
    if ($fillerLen -lt 1) { throw "guardia a offset $off troppo corta ($len B)" }
    $note = " guard-neutralized "
    $padN = $fillerLen - $note.Length
    if ($padN -lt 0) { throw "nota non entra per guardia a offset $off" }
    $halfL = [Math]::Floor($padN / 2)
    $newStr = "{%- if false %}" + ("." * $halfL) + $note + ("." * ($padN - $halfL)) + "{%- endif %}"
    if ($newStr.Length -ne $len) { throw "lunghezza $($newStr.Length) != $len a offset $off" }
    $replacements += @{ off = $off; len = $len; new = $newStr }
    "  #$($replacements.Count) offset=$off len=$len"
}

# --- applica in-place (ordine inverso per preservare offset) ---
$fsw = [System.IO.File]::Open($blob, 'Open', 'ReadWrite')
for ($i = $replacements.Count - 1; $i -ge 0; $i--) {
    $null = $fsw.Seek($replacements[$i].off, 'Begin')
    $nb = [System.Text.Encoding]::ASCII.GetBytes($replacements[$i].new)
    $fsw.Write($nb, 0, $nb.Length)
}
$fsw.Close()
"In-place OK: $($replacements.Count) guardie neutralizzate"

# --- rehash SHA256 ---
$sha = [System.Security.Cryptography.SHA256]::Create()
$s = [System.IO.File]::OpenRead($blob); $b2 = New-Object byte[] (16MB)
while (($r2 = $s.Read($b2, 0, $b2.Length)) -gt 0) { $null = $sha.TransformBlock($b2, 0, $r2, $null, 0) }
$sha.TransformFinalBlock($b2, 0, 0) | Out-Null; $s.Close()
$hash = [System.BitConverter]::ToString($sha.Hash).Replace('-','').ToLower()

# --- rename blob + update manifest ---
Move-Item -Force $blob ("$env:USERPROFILE\.ollama\models\blobs\sha256-" + $hash)
foreach ($l in $m.layers) { if ($l.mediaType -match '\.image\.model') { $l.digest = "sha256:$hash" } }
[System.IO.File]::WriteAllText($mPath, ($m | ConvertTo-Json -Depth 10), (New-Object System.Text.UTF8Encoding $false))
"Fatto: $ModelName -> sha256:$($hash.Substring(0,12))..."
