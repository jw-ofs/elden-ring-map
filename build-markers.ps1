# ============================================================
#  build-markers.ps1
#  Projects datamined Elden Ring data (graces, bosses) onto the
#  master map-tile pixel space, producing markers.js with exact,
#  English, pixel-accurate pins. Ports elden-ring-compass map-affine.ts.
# ============================================================
$ErrorActionPreference = "Stop"
$ua = @{ "User-Agent"="x" }
$base = "https://raw.githubusercontent.com/EthanShoeDev/elden-ring-compass/main/packages/data/src/generated"
$cache = Join-Path $PSScriptRoot "_data"
if (-not (Test-Path $cache)) { New-Item -ItemType Directory -Path $cache -Force | Out-Null }

function Get-Gen($file){
  $p = Join-Path $cache $file
  if (-not (Test-Path $p)) {
    Invoke-WebRequest "$base/$file" -Headers $ua -OutFile $p -UseBasicParsing
  }
  return Get-Content $p -Raw -Encoding UTF8
}
function Get-JsonArray($content){
  $eq = $content.IndexOf(' = ')           # skip the `Foo[]` type annotation before `=`
  $a = $content.IndexOf('[', $eq); $b = $content.LastIndexOf(']')
  $json = $content.Substring($a, $b-$a+1)
  $json = $json -replace ',(\s*)\]\s*$', '$1]'   # drop TS trailing comma before ]
  return $json | ConvertFrom-Json
}
# placements.ts wraps its array in JSON.parse("...") — decode the JS string, then the JSON.
function Get-Placements($content){
  $s = $content.IndexOf('JSON.parse('); $q1 = $content.IndexOf('"', $s); $q2 = $content.LastIndexOf('"')
  $inner = $content.Substring($q1, $q2-$q1+1) | ConvertFrom-Json
  return $inner | ConvertFrom-Json
}
function NameMap($arr){ $h=@{}; foreach($x in $arr){ if(-not $h.ContainsKey([int]$x.id)){ $h[[int]$x.id]=$x.name } }; return $h }

Write-Host "Loading data..."
$graces   = Get-JsonArray (Get-Gen "graces.ts")
$bosses   = Get-JsonArray (Get-Gen "bosses.ts")
$conv     = Get-JsonArray (Get-Gen "world-map-legacy-conv.ts")

# ---- projection (ports map-affine.ts) ----
$OFFSET_X = -7168; $OFFSET_Y = 16640
$convByBlock = @{}
foreach($c in $conv){
  if (-not $convByBlock.ContainsKey($c.srcMapId)) { $convByBlock[$c.srcMapId] = New-Object System.Collections.Generic.List[object] }
  $convByBlock[$c.srcMapId].Add($c)
}
function Project($mapId, $x, $z){
  if ($mapId -match '^m(60|61)_(\d+)_(\d+)_\d(\d)$'){
    $tier = [int]$Matches[4]
    if ($tier -gt 2) { return $null }
    $size = 256 * [math]::Pow(2,$tier)
    $wx = [int]$Matches[2]*$size + $size/2 + $x
    $wz = [int]$Matches[3]*$size + $size/2 + $z
    $master = if ($Matches[1] -eq '60') {'M00'} else {'M10'}
    return [pscustomobject]@{ master=$master; px=($wx+$OFFSET_X); py=($OFFSET_Y-$wz) }
  }
  if ($mapId -match '^(m\d\d_\d\d_\d\d)_'){
    $block = $Matches[1]
    if (-not $convByBlock.ContainsKey($block)) { return $null }
    $best=$null; $bestD=[double]::PositiveInfinity
    foreach($p in $convByBlock[$block]){
      $dx=$x-$p.srcX; $dz=$z-$p.srcZ; $d=$dx*$dx+$dz*$dz
      if ($d -lt $bestD){ $bestD=$d; $best=$p }
    }
    if ($null -eq $best){ return $null }
    return [pscustomobject]@{ master=$best.master; px=($x+$best.addX+$OFFSET_X); py=($OFFSET_Y-($z+$best.addZ)) }
  }
  return $null
}

# ---- grace bonfire positions: scan markers.ts for the needed entityIds ----
Write-Host "Resolving grace positions from markers.ts..."
$needed = @{}
foreach($g in $graces){ $needed["$($g.bonfireEntityId)"] = $true }
$markersPath = Join-Path $cache "markers.ts"
if (-not (Test-Path $markersPath)) { Invoke-WebRequest "$base/markers.ts" -Headers $ua -OutFile $markersPath -UseBasicParsing }
$entityPos = @{}
foreach($line in [System.IO.File]::ReadLines($markersPath)){
  if ($line -match '"entityId":(\d+)'){
    $id = $Matches[1]
    if ($needed.ContainsKey($id) -and -not $entityPos.ContainsKey($id)){
      $obj = ($line.Trim().TrimEnd(',')) | ConvertFrom-Json
      $entityPos[$id] = $obj
    }
  }
}
Write-Host "  resolved $($entityPos.Count) / $($needed.Count) grace entities"

# ---- build pins ----
$pins = New-Object System.Collections.Generic.List[object]
$regionAcc = @{}  # "master|region" -> list of [px,py]
function Slug($s){ ($s -replace '[^a-zA-Z0-9]+','-').Trim('-').ToLower() }

$gOk=0
$graceKept=@{}      # "name|master" -> kept [px,py]; drop co-located same-name graces
$GRACEDUP2 = 12*12  # Leyndell Royal/Ashen capital share grace names AND coords -> one visible pin
foreach($g in $graces){
  $mk = $entityPos["$($g.bonfireEntityId)"]
  if ($null -eq $mk){ continue }
  $p = Project $mk.mapId $mk.x $mk.z
  if ($null -eq $p -or ($p.master -notmatch '^M(00|01|10|11)$')){ continue }
  # region centroid accumulates from every grace (even deduped ones) so labels are unaffected
  if ($g.region){
    $k = "$($p.master)|$($g.region)"
    if (-not $regionAcc.ContainsKey($k)) { $regionAcc[$k]=New-Object System.Collections.Generic.List[object] }
    $regionAcc[$k].Add(@($p.px,$p.py))
  }
  $gk = "$($g.name)|$($p.master)"
  if (-not $graceKept.ContainsKey($gk)) { $graceKept[$gk]=New-Object System.Collections.Generic.List[object] }
  $gdup=$false
  foreach($q in $graceKept[$gk]){ $dx=$p.px-$q[0]; $dy=$p.py-$q[1]; if(($dx*$dx+$dy*$dy) -lt $GRACEDUP2){ $gdup=$true; break } }
  if ($gdup){ continue }
  $graceKept[$gk].Add(@($p.px,$p.py))
  $pins.Add([pscustomobject]@{ id="g$($g.flagId)"; cat='grace'; name=$g.name; master=$p.master; px=[math]::Round($p.px,1); py=[math]::Round($p.py,1); desc=$g.region })
  $gOk++
}

$bOk=0
$bossKept=@{}; $bossSeen=@{}   # flagId -> kept [px,py] / emit count
$BOSSDUP2 = 40*40              # same flag a few px away = one encounter recorded twice
foreach($b in $bosses){
  if (-not $b.name){ continue }
  $p = Project $b.mapId $b.x $b.z
  if ($null -eq $p -or ($p.master -notmatch '^M(00|01|10|11)$')){ continue }
  $fid = "$($b.defeatFlagId)"
  if (-not $bossKept.ContainsKey($fid)) { $bossKept[$fid]=New-Object System.Collections.Generic.List[object] }
  $bdup=$false
  foreach($q in $bossKept[$fid]){ $dx=$p.px-$q[0]; $dy=$p.py-$q[1]; if(($dx*$dx+$dy*$dy) -lt $BOSSDUP2){ $bdup=$true; break } }
  if ($bdup){ continue }
  $bossKept[$fid].Add(@($p.px,$p.py))
  $cnt=[int]$bossSeen[$fid]; $bossSeen[$fid]=$cnt+1
  $bid = if($cnt -eq 0){ "b$fid" } else { "b$fid-$cnt" }   # unique id when one flag has multiple distinct arenas
  $desc = if ($b.runes){ "{0:N0} runes" -f $b.runes } else { "" }
  $pins.Add([pscustomobject]@{ id=$bid; cat='boss'; name=$b.name; master=$p.master; px=[math]::Round($p.px,1); py=[math]::Round($p.py,1); desc=$desc })
  $bOk++
}

# ---- LOOT: items from placements.ts joined to English names ----
Write-Host "Loading items..."
$plac    = Get-Placements (Get-Gen "placements.ts")
$weapons = NameMap (Get-JsonArray (Get-Gen "weapons.ts"))
$talis   = NameMap (Get-JsonArray (Get-Gen "talismans.ts"))
$aow     = NameMap (Get-JsonArray (Get-Gen "ashes-of-war.ts"))
$spirits = NameMap (Get-JsonArray (Get-Gen "spirit-ashes.ts"))
$spells  = NameMap (Get-JsonArray (Get-Gen "spells.ts"))
$armor   = NameMap (Get-JsonArray (Get-Gen "armor.ts"))
$goodsArr = Get-JsonArray (Get-Gen "goods.ts")
$goods=@{}; $goodsCat=@{}
foreach($g in $goodsArr){ $gid=[int]$g.id; if(-not $goods.ContainsKey($gid)){ $goods[$gid]=$g.name; $goodsCat[$gid]=$g.category } }

$kept=@{}; $lootCounts=@{}   # "$cat|$iid|$master" -> list of [px,py] kept; dedupe same item within 80 units
$DEDUP2 = 80*80
# confirmed single-location items the datamined data lists a second (far/misplaced) time -> keep first within 220u
$ONEOF = @('Dexterity-knot Crystal Tear','Leather Headband','Cerulean Crystal Tear','Blessing of the Erdtree')
$oneOfKept=@{}; $ONEOF2 = 220*220
foreach($p in $plac){
  $iid=[int]$p.itemId; $cat=$null; $name=$null
  if    ($p.itemType -eq 'weapon')     { if($p.source -eq 'map' -or $p.source -eq 'event'){ $name=$weapons[$iid]; $cat='weapon' } }
  elseif($p.itemType -eq 'talisman')   { $name=$talis[$iid]; $cat='talisman' }
  elseif($p.itemType -eq 'ash-of-war') { $name=$aow[$iid];   $cat='ash' }
  elseif($p.itemType -eq 'armor')      { if($p.source -eq 'map' -or $p.source -eq 'event'){ $name=$armor[$iid]; $cat='armor' } }
  elseif($p.itemType -eq 'goods'){
    if    ($spirits.ContainsKey($iid)) { $name=$spirits[$iid]; $cat='spirit' }
    elseif($spells.ContainsKey($iid))  { $name=$spells[$iid];  $cat='spell' }
    elseif($goodsCat[$iid] -eq 'Crystal Tear') { $name=$goods[$iid]; $cat='crystal' }
    elseif($goodsCat[$iid] -eq 'Great Rune')   { $name=$goods[$iid]; $cat='greatrune' }
    else {
      $gn=$goods[$iid]
      if    ($gn -eq 'Golden Seed')  { $name=$gn; $cat='golden' }
      elseif($gn -eq 'Sacred Tear')  { $name=$gn; $cat='tear' }
      elseif($gn -eq 'Larval Tear')  { $name=$gn; $cat='larval' }
      elseif($gn -eq 'Memory Stone') { $name=$gn; $cat='memory' }
      elseif($gn -match 'Whetblade') { $name=$gn; $cat='whetblade' }
    }
  }
  if(-not $cat -or -not $name){ continue }
  if($name -match 'dummy|^\[ERROR' -or $name.Trim() -eq ''){ continue }
  $pr = Project $p.mapId $p.x $p.z
  if($null -eq $pr -or ($pr.master -notmatch '^M(00|01|10|11)$')){ continue }
  # dedupe the same item placed within 80 units (stacked lot rows = one physical pickup)
  $kk = "$cat|$iid|$($pr.master)"
  if(-not $kept.ContainsKey($kk)){ $kept[$kk]=New-Object System.Collections.Generic.List[object] }
  $dup=$false
  foreach($p2 in $kept[$kk]){ $dx=$pr.px-$p2[0]; $dy=$pr.py-$p2[1]; if(($dx*$dx+$dy*$dy) -lt $DEDUP2){ $dup=$true; break } }
  if($dup){ continue }
  $kept[$kk].Add(@([double]$pr.px,[double]$pr.py))
  if($ONEOF -contains $name){
    $ok="$name|$($pr.master)"
    if(-not $oneOfKept.ContainsKey($ok)){ $oneOfKept[$ok]=New-Object System.Collections.Generic.List[object] }
    $oskip=$false
    foreach($q in $oneOfKept[$ok]){ $dx=$pr.px-$q[0]; $dy=$pr.py-$q[1]; if(($dx*$dx+$dy*$dy) -lt $ONEOF2){ $oskip=$true; break } }
    if($oskip){ continue }
    $oneOfKept[$ok].Add(@([double]$pr.px,[double]$pr.py))
  }
  $src = switch($p.source){ 'map'{'Treasure'} 'enemy'{'Enemy drop'} 'event'{'Event reward'} default{"$($p.source)"} }
  if($p.quantity -gt 1){ $src = "$src x$($p.quantity)" }
  $pins.Add([pscustomobject]@{ id="i$($pins.Count)"; cat=$cat; name=$name; master=$pr.master; px=[math]::Round($pr.px,1); py=[math]::Round($pr.py,1); desc=$src })
  $lootCounts[$cat] = [int]$lootCounts[$cat] + 1
}
Write-Host ("Loot pins: " + (($lootCounts.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join " "))

# ---- QUEST NPCs: named NPC spawn locations from markers.ts ----
# Each questline NPC appears at one or more spots; we place a pin per distinct
# location (coarse-deduped) labelled with the NPC's English name.
Write-Host "Resolving quest-NPC locations..."
$npcKept=@{}; $npcCount=0; $NPCDEDUP2 = 140*140   # one pin per NPC per distinct spot (within 140 units)
foreach($line in [System.IO.File]::ReadLines($markersPath)){
  if($line -notmatch '"category":"npc"'){ continue }
  if($line -notmatch '"displayName":"'){ continue }   # skip null displayName
  $obj = ($line.Trim().TrimEnd(',')) | ConvertFrom-Json
  if(-not $obj.displayName){ continue }
  $pr = Project $obj.mapId $obj.x $obj.z
  if($null -eq $pr -or ($pr.master -notmatch '^M(00|01|10|11)$')){ continue }
  $kk = "$($obj.displayName)|$($pr.master)"
  if(-not $npcKept.ContainsKey($kk)){ $npcKept[$kk]=New-Object System.Collections.Generic.List[object] }
  $dup=$false
  foreach($p2 in $npcKept[$kk]){ $dx=$pr.px-$p2[0]; $dy=$pr.py-$p2[1]; if(($dx*$dx+$dy*$dy) -lt $NPCDEDUP2){ $dup=$true; break } }
  if($dup){ continue }
  $npcKept[$kk].Add(@([double]$pr.px,[double]$pr.py))
  $pins.Add([pscustomobject]@{ id="n$($pins.Count)"; cat='npc'; name=$obj.displayName; master=$pr.master; px=[math]::Round($pr.px,1); py=[math]::Round($pr.py,1); desc="Quest / NPC location" })
  $npcCount++
}
Write-Host "Quest-NPC pins: $npcCount"

# region label pins = centroid of that region's graces
foreach($k in $regionAcc.Keys){
  $parts=$k.Split('|'); $master=$parts[0]; $region=$parts[1]
  $list=$regionAcc[$k]
  $cx=($list | ForEach-Object { $_[0] } | Measure-Object -Average).Average
  $cy=($list | ForEach-Object { $_[1] } | Measure-Object -Average).Average
  $pins.Add([pscustomobject]@{ id="r-$master-$(Slug $region)"; cat='region'; name=$region; master=$master; px=[math]::Round($cx,1); py=[math]::Round($cy,1); desc="" })
}

Write-Host "Pins: graces=$gOk bosses=$bOk regions=$($regionAcc.Count) total=$($pins.Count)"

# ---- drop non-physical placement buckets ----
# Shop/event placements with a sentinel coordinate stack many unrelated items on one exact
# point (e.g. 20 quest/boss/remembrance rewards dumped at Ainsel River). Signature: >=6 distinct
# items spanning >=3 loot categories at one identical rounded coord. Real treasure never does this.
$lootCats = @('weapon','armor','talisman','spirit','spell','ash','crystal','golden','tear','larval','memory','greatrune','whetblade')
$coordGroups=@{}
foreach($p in $pins){
  if($lootCats -notcontains $p.cat){ continue }
  $k="$($p.master)|$([math]::Round($p.px))|$([math]::Round($p.py))"
  if(-not $coordGroups.ContainsKey($k)){ $coordGroups[$k]=New-Object System.Collections.Generic.List[object] }
  $coordGroups[$k].Add($p)
}
$badCoords=@{}
foreach($k in $coordGroups.Keys){
  $grp=$coordGroups[$k]
  $names=@($grp | ForEach-Object { $_.name } | Sort-Object -Unique)
  $cats =@($grp | ForEach-Object { $_.cat }  | Sort-Object -Unique)
  if($names.Count -ge 6 -and $cats.Count -ge 3){ $badCoords[$k]=$grp.Count }
}
if($badCoords.Count){
  $before=$pins.Count
  $filtered=New-Object System.Collections.Generic.List[object]
  foreach($p in $pins){
    if($lootCats -contains $p.cat){
      $k="$($p.master)|$([math]::Round($p.px))|$([math]::Round($p.py))"
      if($badCoords.ContainsKey($k)){ continue }
    }
    $filtered.Add($p)
  }
  $pins=$filtered
  Write-Host "Dropped non-physical buckets: $($badCoords.Count) coords / $($before-$pins.Count) item pins"
  foreach($k in $badCoords.Keys){ Write-Host "   [$k] x$($badCoords[$k])" }
}

# ---- emit markers.js ----
$fire =[char]::ConvertFromUtf32(0x1F525)
$skull=[char]::ConvertFromUtf32(0x1F480)
$pin  =[char]::ConvertFromUtf32(0x1F4CD)
$sword=[char]::ConvertFromUtf32(0x2694)
$tali =[char]::ConvertFromUtf32(0x1F531)
$scrol=[char]::ConvertFromUtf32(0x1F4DC)
$ghost=[char]::ConvertFromUtf32(0x1F47B)
$ball =[char]::ConvertFromUtf32(0x1F52E)
$seed =[char]::ConvertFromUtf32(0x1F331)
$drop =[char]::ConvertFromUtf32(0x1F4A7)
$shield=[char]::ConvertFromUtf32(0x1F6E1)
$tube =[char]::ConvertFromUtf32(0x1F9EA)
$mage =[char]::ConvertFromUtf32(0x1F9D9)
$larva=[char]::ConvertFromUtf32(0x1F41B)
$brain=[char]::ConvertFromUtf32(0x1F9E0)
$ring =[char]::ConvertFromUtf32(0x1F48D)
$dagger=[char]::ConvertFromUtf32(0x1F5E1)
$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine("/* AUTO-GENERATED by build-markers.ps1 - pixel-accurate pins projected from")
[void]$sb.AppendLine("   datamined Elden Ring data (elden-ring-compass). master M00=overworld, M01=underground.")
[void]$sb.AppendLine("   px,py = pixel on the 10496x10496 master tile image (unproject at native zoom). */")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("const CATEGORIES = [")
[void]$sb.AppendLine("  { group:""Progress"", id:""grace"",  name:""Sites of Grace"", icon:""$fire"", color:""#d9a441"" },")
[void]$sb.AppendLine("  { group:""Progress"", id:""boss"",   name:""Bosses"",         icon:""$skull"", color:""#c0504d"" },")
[void]$sb.AppendLine("  { group:""Quests & NPCs"", id:""npc"", name:""Quest NPCs"",  icon:""$mage"", color:""#b07acc"" },")
[void]$sb.AppendLine("  { group:""Gear"", id:""weapon"",   name:""Weapons"",        icon:""$sword"", color:""#4a90d9"" },")
[void]$sb.AppendLine("  { group:""Gear"", id:""talisman"", name:""Talismans"",      icon:""$tali"", color:""#d98841"" },")
[void]$sb.AppendLine("  { group:""Gear"", id:""spirit"",   name:""Spirit Ashes"",   icon:""$ghost"", color:""#6fb1c4"" },")
[void]$sb.AppendLine("  { group:""Gear"", id:""ash"",      name:""Ashes of War"",   icon:""$scrol"", color:""#3d9970"" },")
[void]$sb.AppendLine("  { group:""Gear"", id:""spell"",    name:""Sorceries & Incantations"", icon:""$ball"", color:""#9b6dd1"" },")
[void]$sb.AppendLine("  { group:""Gear"", id:""armor"",    name:""Armor"",          icon:""$shield"", color:""#8a8f98"" },")
[void]$sb.AppendLine("  { group:""Upgrades"", id:""golden"", name:""Golden Seeds"",  icon:""$seed"", color:""#cbb12b"" },")
[void]$sb.AppendLine("  { group:""Upgrades"", id:""tear"",   name:""Sacred Tears"",  icon:""$drop"", color:""#5b9bd5"" },")
[void]$sb.AppendLine("  { group:""Upgrades"", id:""crystal"",name:""Crystal Tears"", icon:""$tube"", color:""#c77dd6"" },")
[void]$sb.AppendLine("  { group:""Key Items"", id:""greatrune"", name:""Great Runes"",   icon:""$ring"", color:""#e0c341"" },")
[void]$sb.AppendLine("  { group:""Key Items"", id:""larval"",    name:""Larval Tears"",  icon:""$larva"", color:""#c98fd6"" },")
[void]$sb.AppendLine("  { group:""Key Items"", id:""memory"",    name:""Memory Stones"", icon:""$brain"", color:""#6fa8dc"" },")
[void]$sb.AppendLine("  { group:""Key Items"", id:""whetblade"", name:""Whetblades"",    icon:""$dagger"", color:""#b0b3b8"" },")
[void]$sb.AppendLine("  { group:""Reference"", id:""region"", name:""Region Labels"", icon:""$pin"", color:""#586274"" },")
[void]$sb.AppendLine("];")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("const MARKERS = [")
foreach($p in $pins){
  $name = ($p.name -replace '\\','\\' -replace '"','\"')
  $desc = ($p.desc -replace '\\','\\' -replace '"','\"')
  [void]$sb.AppendLine("  { id:""$($p.id)"", cat:""$($p.cat)"", name:""$name"", master:""$($p.master)"", px:$($p.px), py:$($p.py), desc:""$desc"" },")
}
[void]$sb.AppendLine("];")
Set-Content -Path (Join-Path $PSScriptRoot "markers.js") -Value $sb.ToString() -Encoding UTF8
Write-Host "Wrote markers.js ($($pins.Count) pins)"
