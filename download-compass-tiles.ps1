# Download the datamined master map tiles (M00 overworld + M01 underground)
# from the elden-ring-compass repo for pixel-accurate marker alignment.
param([int]$Concurrency = 24)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http
$dest = Join-Path $PSScriptRoot "ctiles"
$ua = @{ "User-Agent"="x" }

$tree = Invoke-RestMethod "https://api.github.com/repos/EthanShoeDev/elden-ring-compass/git/trees/main?recursive=1" -Headers $ua
$blobs = $tree.tree | Where-Object { $_.path -match 'map-tiles/(M00|M01|M10|M11)/.*\.webp$' }
"To download: $($blobs.Count) tiles (M00/M01 Lands Between + M10/M11 Land of Shadow DLC)"

$handler = New-Object System.Net.Http.HttpClientHandler
$handler.MaxConnectionsPerServer = $Concurrency
$client = New-Object System.Net.Http.HttpClient($handler)
$client.DefaultRequestHeaders.Add("User-Agent","x")
$client.Timeout = [TimeSpan]::FromSeconds(40)

$arr = @($blobs)
$done=0; $dl=0; $skip=0; $fail=0; $i=0
while ($i -lt $arr.Count) {
  $batch = $arr[$i..([math]::Min($i+$Concurrency-1, $arr.Count-1))]
  $tasks=@()
  foreach($b in $batch){
    $rel = $b.path -replace '^packages/data/images/map-tiles/',''
    $local = Join-Path $dest ($rel -replace '/','\')
    if (Test-Path $local) { $skip++; continue }
    $dir = Split-Path $local -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $url = "https://raw.githubusercontent.com/EthanShoeDev/elden-ring-compass/main/$($b.path)"
    $tasks += [pscustomobject]@{ Local=$local; Task=$client.GetByteArrayAsync($url) }
  }
  foreach($t in $tasks){
    try { [System.IO.File]::WriteAllBytes($t.Local, $t.Task.Result); $dl++ }
    catch { $fail++ }
  }
  $i += $Concurrency
  $done = [math]::Min($i, $arr.Count)
  Write-Progress -Activity "Downloading compass tiles" -Status "$done / $($arr.Count)" -PercentComplete (100.0*$done/$arr.Count)
}
$mb = [math]::Round(((Get-ChildItem $dest -Recurse -File | Measure-Object Length -Sum).Sum/1MB),1)
"Done. downloaded=$dl skipped=$skip failed=$fail  size=$mb MB at $dest"
