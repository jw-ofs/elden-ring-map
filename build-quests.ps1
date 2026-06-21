# ============================================================
#  build-quests.ps1
#  Authored, ORDERED questline steps. Each step is anchored to the
#  ACTUAL task location:
#    ty=item  -> the item's real pickup coordinate (placements.ts)
#    ty=boss  -> the boss arena
#    ty=npc   -> the NPC's location (nearest along the route)
#    ty=grace -> an area/travel waypoint
#  Anchors inherit pixel-accurate coordinates. Outputs quests.js.
# ============================================================
$ErrorActionPreference = "Stop"
$ua = @{ "User-Agent"="x" }
$cache = Join-Path $PSScriptRoot "_data"
function Get-Gen($f){ $p=Join-Path $cache $f; if(-not(Test-Path $p)){ Invoke-WebRequest "https://raw.githubusercontent.com/EthanShoeDev/elden-ring-compass/main/packages/data/src/generated/$f" -Headers $ua -OutFile $p -UseBasicParsing }; Get-Content $p -Raw -Encoding UTF8 }
function Get-JsonArray($c){ $eq=$c.IndexOf(' = '); $a=$c.IndexOf('[',$eq); $b=$c.LastIndexOf(']'); ($c.Substring($a,$b-$a+1) -replace ',(\s*)\]\s*$','$1]') | ConvertFrom-Json }
function Get-Placements($c){ $s=$c.IndexOf('JSON.parse('); $q1=$c.IndexOf('"',$s); $q2=$c.LastIndexOf('"'); ($c.Substring($q1,$q2-$q1+1) | ConvertFrom-Json) | ConvertFrom-Json }
function NameMap($arr){ $h=@{}; foreach($x in $arr){ if(-not $h.ContainsKey([int]$x.id)){ $h[[int]$x.id]=$x.name } }; return $h }

# ---- projection (ports map-affine.ts) ----
$OFFSET_X=-7168; $OFFSET_Y=16640
$conv = Get-JsonArray (Get-Gen "world-map-legacy-conv.ts")
$convByBlock=@{}
foreach($c in $conv){ if(-not $convByBlock.ContainsKey($c.srcMapId)){ $convByBlock[$c.srcMapId]=New-Object System.Collections.Generic.List[object] }; $convByBlock[$c.srcMapId].Add($c) }
function Project($mapId,$x,$z){
  if($mapId -match '^m(60|61)_(\d+)_(\d+)_\d(\d)$'){
    $tier=[int]$Matches[4]; if($tier -gt 2){ return $null }
    $size=256*[math]::Pow(2,$tier)
    $wx=[int]$Matches[2]*$size+$size/2+$x; $wz=[int]$Matches[3]*$size+$size/2+$z
    $master= if($Matches[1] -eq '60'){'M00'}else{'M10'}
    return [pscustomobject]@{ master=$master; px=($wx+$OFFSET_X); py=($OFFSET_Y-$wz) }
  }
  if($mapId -match '^(m\d\d_\d\d_\d\d)_'){
    $block=$Matches[1]; if(-not $convByBlock.ContainsKey($block)){ return $null }
    $best=$null; $bd=[double]::PositiveInfinity
    foreach($p in $convByBlock[$block]){ $dx=$x-$p.srcX;$dz=$z-$p.srcZ;$d=$dx*$dx+$dz*$dz; if($d -lt $bd){$bd=$d;$best=$p} }
    if($null -eq $best){ return $null }
    return [pscustomobject]@{ master=$best.master; px=($x+$best.addX+$OFFSET_X); py=($OFFSET_Y-($z+$best.addZ)) }
  }
  return $null
}

# ---- item placements -> name(lower) => list of {master,px,py} ----
Write-Host "Building item-location index..."
$plac    = Get-Placements (Get-Gen "placements.ts")
$weapons = NameMap (Get-JsonArray (Get-Gen "weapons.ts"))
$talis   = NameMap (Get-JsonArray (Get-Gen "talismans.ts"))
$aow     = NameMap (Get-JsonArray (Get-Gen "ashes-of-war.ts"))
$armor   = NameMap (Get-JsonArray (Get-Gen "armor.ts"))
$goods   = NameMap (Get-JsonArray (Get-Gen "goods.ts"))
$itemMap = New-Object 'System.Collections.Generic.Dictionary[string,System.Collections.Generic.List[object]]'
foreach($p in $plac){
  $iid=[int]$p.itemId; $nm=$null
  switch($p.itemType){
    'weapon'    { $nm=$weapons[$iid] }
    'talisman'  { $nm=$talis[$iid] }
    'ash-of-war'{ $nm=$aow[$iid] }
    'armor'     { $nm=$armor[$iid] }
    'goods'     { $nm=$goods[$iid] }
  }
  if(-not $nm){ continue }
  $pr=Project $p.mapId $p.x $p.z
  if($null -eq $pr -or ($pr.master -ne 'M00' -and $pr.master -ne 'M01')){ continue }
  $k=([string]$nm).ToLower()
  if(-not $itemMap.ContainsKey($k)){ $itemMap[$k]=New-Object 'System.Collections.Generic.List[object]' }
  $itemMap[$k].Add($pr)
}
Write-Host "  indexed $($itemMap.Count) distinct item names"

# ---- markers.js anchors (grace/boss/npc/region) ----
$mk = Get-Content "$PSScriptRoot\markers.js" -Raw -Encoding UTF8
$markers = New-Object System.Collections.Generic.List[object]
foreach($m in [regex]::Matches($mk, '\{ id:"[^"]*", cat:"([^"]*)", name:"((?:[^"\\]|\\.)*)", master:"([^"]*)", px:([-0-9.]+), py:([-0-9.]+)')){
  $markers.Add([pscustomobject]@{ cat=$m.Groups[1].Value; name=$m.Groups[2].Value; master=$m.Groups[3].Value; px=[double]$m.Groups[4].Value; py=[double]$m.Groups[5].Value })
}

$unresolved=New-Object System.Collections.Generic.List[string]
function Nearest($cands,$prev){
  $arr=@($cands)
  if($arr.Count -eq 0){ return $null }
  if($arr.Count -gt 1 -and $null -ne $prev){
    $px=[double]$prev.px; $py=[double]$prev.py
    $arr=@($arr | Sort-Object { ([double]$_.px-$px)*([double]$_.px-$px)+([double]$_.py-$py)*([double]$_.py-$py) })
  }
  return $arr[0]
}
function Norm($s){
  # strip diacritics (Jolán -> Jolan) so accented marker names match plain anchors
  $d = $s.Normalize([Text.NormalizationForm]::FormD)
  $sb = New-Object System.Text.StringBuilder
  foreach($ch in $d.ToCharArray()){
    if([Globalization.CharUnicodeInfo]::GetUnicodeCategory($ch) -ne [Globalization.UnicodeCategory]::NonSpacingMark){ [void]$sb.Append($ch) }
  }
  return (($sb.ToString() -replace '[^a-zA-Z0-9]','')).ToLower()
}
function Find-Marker($name){
  $c=@($markers | Where-Object { $_.name -ieq $name })
  if($c.Count -eq 0){ $c=@($markers | Where-Object { $_.name -like "*$name*" }) }
  if($c.Count -eq 0){ $n=Norm $name; if($n.Length -ge 4){ $c=@($markers | Where-Object { (Norm $_.name).Contains($n) }) } }
  if($c.Count){ return $c[0] }
  return $null
}
function Resolve-Anchor($name,$type,$prev,$near){
  # disambiguate by the per-step location hint, else the previous step
  $nearMarker = $null
  if($near){ $nearMarker = Find-Marker $near }
  $ref = if($nearMarker){ $nearMarker } else { $prev }
  if($type -eq 'item'){
    $k=$name.ToLower()
    if($itemMap.ContainsKey($k)){ $c=$itemMap[$k].ToArray(); return (Nearest $c $ref) }
    $unresolved.Add("item:$name"); if($nearMarker){ return $nearMarker } else { return $prev }   # reward not world-placed -> use the location
  }
  $cands=@($markers | Where-Object { $_.name -ieq $name -and ($type -eq '' -or $_.cat -eq $type) })
  if($cands.Count -eq 0){ $cands=@($markers | Where-Object { $_.name -ieq $name }) }
  if($cands.Count -eq 0){ $cands=@($markers | Where-Object { $_.name -like "*$name*" -and ($type -eq '' -or $_.cat -eq $type) }) }
  if($cands.Count -eq 0){ $cands=@($markers | Where-Object { $_.name -like "*$name*" }) }
  if($cands.Count -eq 0){ $nn=Norm $name; if($nn.Length -ge 4){ $cands=@($markers | Where-Object { (Norm $_.name).Contains($nn) -and ($type -eq '' -or $_.cat -eq $type) }) } }
  if($cands.Count -eq 0){ $nn=Norm $name; if($nn.Length -ge 4){ $cands=@($markers | Where-Object { (Norm $_.name).Contains($nn) }) } }
  if($cands.Count -eq 0){ $unresolved.Add("$type`:$name"); if($nearMarker){ return $nearMarker } else { return $prev } }
  return (Nearest $cands $ref)
}

# ---- questline definitions (authored + agent-reviewed) ----
$QL = Get-Content "$PSScriptRoot\questlines.json" -Raw -Encoding UTF8 | ConvertFrom-Json

# ---- resolve + emit ----
$sb=New-Object System.Text.StringBuilder
[void]$sb.AppendLine("/* AUTO-GENERATED by build-quests.ps1 - ordered questline steps, each anchored")
[void]$sb.AppendLine("   to the actual task location (item pickup / boss arena / NPC / area). */")
[void]$sb.AppendLine("window.QUESTLINES = [")
foreach($q in $QL){
  $qov  = if($q.overview){ ($q.overview -replace '\\','\\' -replace '"','\"' -replace "\r?\n"," ") } else { "" }
  $qpre = if($q.prereq){   ($q.prereq   -replace '\\','\\' -replace '"','\"' -replace "\r?\n"," ") } else { "" }
  [void]$sb.AppendLine("  { id:""$($q.id)"", name:""$($q.name)"", color:""$($q.color)"", phase:$($q.phase), ord:$($q.ord), overview:""$qov"", prereq:""$qpre"", steps:[")
  $prev=$null; $n=0
  foreach($s in $q.steps){
    $r=Resolve-Anchor $s.anchor $s.type $prev $s.near
    if($null -eq $r){ Write-Host "  UNRESOLVED [$($q.id)] $($s.type):$($s.anchor)" -ForegroundColor Yellow; continue }
    $prev=$r; $n++
    $title=($s.title -replace '\\','\\' -replace '"','\"')
    $desc =($s.desc -replace '\\','\\' -replace '"','\"')
    $warn = if($s.warn){ ($s.warn -replace '\\','\\' -replace '"','\"') } else { "" }
    $reward = if($s.reward){ ($s.reward -replace '\\','\\' -replace '"','\"' -replace "\r?\n"," ") } else { "" }
    [void]$sb.AppendLine("    { n:$n, title:""$title"", desc:""$desc"", warn:""$warn"", reward:""$reward"", kind:""$($s.type)"", master:""$($r.master)"", px:$([math]::Round($r.px,1)), py:$([math]::Round($r.py,1)) },")
  }
  [void]$sb.AppendLine("  ]},")
}
[void]$sb.AppendLine("];")
Set-Content -Path "$PSScriptRoot\quests.js" -Value $sb.ToString() -Encoding UTF8
Write-Host "Wrote quests.js : $($QL.Count) questlines, $($unresolved.Count) unresolved"
if($unresolved.Count){ $unresolved | ForEach-Object { Write-Host "   - $_" } }
