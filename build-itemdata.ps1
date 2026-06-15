# ============================================================
#  build-itemdata.ps1
#  Builds itemdata.js (per-marker stats for rich popups) from the
#  datamined data, and downloads the in-game item icons it needs.
# ============================================================
$ErrorActionPreference="Stop"
Add-Type -AssemblyName System.Net.Http
$ua=@{ "User-Agent"="x" }
$cache="$PSScriptRoot\_data"
$RAW="https://raw.githubusercontent.com/EthanShoeDev/elden-ring-compass/main"
function Gen($f){ $p=Join-Path $cache $f; if(-not(Test-Path $p)){ Invoke-WebRequest "$RAW/packages/data/src/generated/$f" -Headers $ua -OutFile $p -UseBasicParsing }; Get-Content $p -Raw -Encoding UTF8 }
function Arr($c){ $eq=$c.IndexOf(' = '); $a=$c.IndexOf('[',$eq); $b=$c.LastIndexOf(']'); ($c.Substring($a,$b-$a+1) -replace ',(\s*)\]\s*$','$1]') | ConvertFrom-Json }
function ArrJP($c){ if($c.Contains('JSON.parse(')){ $s=$c.IndexOf('JSON.parse('); $q1=$c.IndexOf('"',$s); $q2=$c.LastIndexOf('"'); return ($c.Substring($q1,$q2-$q1+1) | ConvertFrom-Json) | ConvertFrom-Json } else { return Arr $c } }
function Grade($v){ $v=[double]$v; if($v -le 0){ return $null }; if($v -lt 0.25){'E'}elseif($v -lt 0.6){'D'}elseif($v -lt 0.9){'C'}elseif($v -lt 1.4){'B'}elseif($v -lt 1.75){'A'}else{'S'} }

# which (cat,name) actually appear as markers
$mk = Get-Content "$PSScriptRoot\markers.js" -Raw -Encoding UTF8
$present=@{}
foreach($m in [regex]::Matches($mk, 'cat:"([^"]*)", name:"((?:[^"\\]|\\.)*)"')){
  $c=$m.Groups[1].Value; $n=($m.Groups[2].Value -replace '\\"','"' -replace '\\\\','\')
  if(-not $present.ContainsKey($c)){ $present[$c]=@{} }
  $present[$c][$n]=$true
}
function Has($c,$n){ $present.ContainsKey($c) -and $present[$c].ContainsKey($n) }

$ID=@{ weapon=@{}; talisman=@{}; spell=@{}; spirit=@{}; armor=@{}; ash=@{}; golden=@{}; tear=@{}; crystal=@{}; greatrune=@{}; larval=@{}; memory=@{}; whetblade=@{}; boss=@{}; grace=@{} }
$iconSet=@{}
function Trim2($s,$n){ if($s -and $s.Length -gt $n){ return $s.Substring(0,$n).TrimEnd()+'...' } return $s }
function Req($o){
  $p=@()
  if([int]$o.reqStrength    -gt 0){ $p+="Str $([int]$o.reqStrength)" }
  if([int]$o.reqDexterity   -gt 0){ $p+="Dex $([int]$o.reqDexterity)" }
  if([int]$o.reqIntelligence-gt 0){ $p+="Int $([int]$o.reqIntelligence)" }
  if([int]$o.reqFaith       -gt 0){ $p+="Fai $([int]$o.reqFaith)" }
  if([int]$o.reqArcane      -gt 0){ $p+="Arc $([int]$o.reqArcane)" }
  return ($p -join ' / ')
}
function Ico($ic){ if($null -ne $ic -and [int]$ic -gt 0){ $iconSet["$([int]$ic)"]=$true; return [int]$ic } return 0 }

$scById=@{}; $SC=ArrJP (Gen "weapon-scaling.ts"); foreach($s in $SC){ if(-not $scById.ContainsKey([int]$s.id)){ $scById[[int]$s.id]=$s } }
$D=Arr (Gen "weapons.ts")
foreach($w in $D){
  if(-not (Has 'weapon' $w.name)){ continue }
  $atk=@{}; $scl=@{}
  $s=$scById[[int]$w.id]
  if($s){
    foreach($p in $s.baseAttack.PSObject.Properties){ if($p.Value){ $atk[$p.Name]=[int][math]::Round([double]$p.Value) } }
    foreach($p in $s.scaling.PSObject.Properties){ $g=Grade $p.Value; if($g){ $scl[$p.Name]=$g } }
  }
  $ID.weapon[$w.name]=@{ t=$w.category; wt=$w.weight; req=(Req $w); atk=$atk; scl=$scl; inf=[bool]$w.allowAshOfWar; buf=[bool]$w.isBuffable; som=[bool]($w.upgradeMaterial -match 'Somber'); icon=(Ico $w.icon); sum=(Trim2 $w.summary 110) }
}
$D=Arr (Gen "talismans.ts");    foreach($x in $D){ if(Has 'talisman' $x.name){ $ID.talisman[$x.name]=@{ wt=$x.weight; icon=(Ico $x.icon); sum=(Trim2 $x.summary 150) } } }
$D=Arr (Gen "spells.ts");       foreach($x in $D){ if(Has 'spell' $x.name){ $ID.spell[$x.name]=@{ t=$x.category; fp=$x.fpCost; slots=$x.slotsUsed; req=(Req $x); icon=(Ico $x.icon); sum=(Trim2 $x.summary 150) } } }
$D=Arr (Gen "spirit-ashes.ts"); foreach($x in $D){ if(Has 'spirit' $x.name){ $ID.spirit[$x.name]=@{ fp=$x.fpCost; hp=$x.hpCost; mat=$x.upgradeMaterial; icon=(Ico $x.icon); sum=(Trim2 $x.summary 150) } } }
$D=Arr (Gen "armor.ts")
foreach($x in $D){
  if(-not (Has 'armor' $x.name)){ continue }
  $ID.armor[$x.name]=@{ wt=$x.weight; poise=$x.poise;
    neg=@{ ph=[math]::Round([double]$x.negationPhysical,1); st=[math]::Round([double]$x.negationStrike,1); sl=[math]::Round([double]$x.negationSlash,1); pi=[math]::Round([double]$x.negationPierce,1); ma=[math]::Round([double]$x.negationMagic,1); fi=[math]::Round([double]$x.negationFire,1); li=[math]::Round([double]$x.negationLightning,1); ho=[math]::Round([double]$x.negationHoly,1) };
    res=@{ im=[int]$x.resistPoison; ro=[int]$x.resistBleed; fo=[int]$x.resistSleep; de=[int]$x.resistDeath };
    icon=(Ico $x.icon); sum=(Trim2 $x.summary 110) }
}
$D=Arr (Gen "ashes-of-war.ts"); foreach($x in $D){ if(Has 'ash' $x.name){ $ID.ash[$x.name]=@{ aff=$x.defaultAffinity; icon=(Ico $x.icon); sum=(Trim2 $x.summary 150) } } }
$goodsByName=@{}; $D=Arr (Gen "goods.ts"); foreach($g in $D){ if(-not $goodsByName.ContainsKey($g.name)){ $goodsByName[$g.name]=$g } }
foreach($catn in 'golden','tear','crystal','greatrune','larval','memory','whetblade'){ if(-not $present.ContainsKey($catn)){ continue }; foreach($nm in $present[$catn].Keys){ $g=$goodsByName[$nm]; if($g){ $ID[$catn][$nm]=@{ icon=(Ico $g.icon); sum=(Trim2 $g.summary 170) } } } }
$D=Arr (Gen "bosses.ts");       foreach($b in $D){ if($b.name -and (Has 'boss' $b.name) -and -not $ID.boss.ContainsKey($b.name)){ $ID.boss[$b.name]=@{ runes=[int]$b.runes } } }
$D=Arr (Gen "graces.ts");       foreach($g in $D){ if((Has 'grace' $g.name) -and -not $ID.grace.ContainsKey($g.name)){ $ID.grace[$g.name]=@{ region=$g.region } } }

"window.ITEMDATA = " + ($ID | ConvertTo-Json -Depth 6 -Compress) | Set-Content "$PSScriptRoot\itemdata.js" -Encoding UTF8
$entries=0; foreach($k in $ID.Keys){ $entries += $ID[$k].Count }
"itemdata.js written: $entries entries, $($iconSet.Count) icons needed"

# download icons
$dest=Join-Path $PSScriptRoot "icons"
if(-not(Test-Path $dest)){ New-Item -ItemType Directory $dest | Out-Null }
$handler=New-Object System.Net.Http.HttpClientHandler; $handler.MaxConnectionsPerServer=24
$client=New-Object System.Net.Http.HttpClient($handler); $client.DefaultRequestHeaders.Add("User-Agent","x"); $client.Timeout=[TimeSpan]::FromSeconds(30)
$ids=@($iconSet.Keys); $i=0; $dl=0; $skip=0; $fail=0
while($i -lt $ids.Count){
  $batch=$ids[$i..([math]::Min($i+23,$ids.Count-1))]
  $tasks=@()
  foreach($id in $batch){ $lp=Join-Path $dest "$id.webp"; if(Test-Path $lp){ $skip++; continue }; $tasks+=[pscustomobject]@{ Local=$lp; Task=$client.GetByteArrayAsync("$RAW/packages/data/images/icons/items/$id.webp") } }
  foreach($t in $tasks){ try{ [System.IO.File]::WriteAllBytes($t.Local,$t.Task.Result); $dl++ }catch{ $fail++ } }
  $i+=24
}
$mb=[math]::Round(((Get-ChildItem $dest -File | Measure-Object Length -Sum).Sum/1MB),1)
"icons: downloaded=$dl skipped=$skip failed=$fail  ($mb MB)"
