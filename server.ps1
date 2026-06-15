# Concurrent static file server for previewing the map locally.
# Multiple worker threads share one HttpListener (HttpListener allows
# concurrent GetContext calls), so bursts of tile requests serve in parallel.
param([int]$Port = 8777, [int]$Workers = 12)
$root = $PSScriptRoot
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:$Port/")
$listener.Start()
Write-Host "Serving $root on http://localhost:$Port/ ($Workers workers)"

$worker = {
  param($listener, $root)
  $mime = @{
    ".html"="text/html; charset=utf-8"; ".js"="application/javascript; charset=utf-8";
    ".css"="text/css"; ".jpg"="image/jpeg"; ".jpeg"="image/jpeg"; ".png"="image/png";
    ".webp"="image/webp"; ".json"="application/json"; ".svg"="image/svg+xml"
  }
  while ($listener.IsListening) {
    try {
      $ctx = $listener.GetContext()
      $rel = [System.Uri]::UnescapeDataString($ctx.Request.Url.AbsolutePath).TrimStart("/")
      if ([string]::IsNullOrEmpty($rel)) { $rel = "index.html" }
      $path = Join-Path $root ($rel -replace '/','\')
      if ($ctx.Request.HttpMethod -eq 'PUT') {
        $dir = Split-Path $path -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $ms = New-Object System.IO.MemoryStream
        $ctx.Request.InputStream.CopyTo($ms)
        [System.IO.File]::WriteAllBytes($path, $ms.ToArray())
        $ms.Dispose()
        $ctx.Response.StatusCode = 200
        $ctx.Response.OutputStream.Close()
        continue
      }
      if (Test-Path $path -PathType Leaf) {
        $ext = [System.IO.Path]::GetExtension($path).ToLower()
        $ct = $mime[$ext]; if (-not $ct) { $ct = "application/octet-stream" }
        $bytes = [System.IO.File]::ReadAllBytes($path)
        $ctx.Response.ContentType = $ct
        $ctx.Response.ContentLength64 = $bytes.Length
        $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
      } else { $ctx.Response.StatusCode = 404 }
      $ctx.Response.OutputStream.Close()
    } catch {}
  }
}

$pool = @()
for ($i = 0; $i -lt $Workers; $i++) {
  $ps = [powershell]::Create()
  [void]$ps.AddScript($worker).AddArgument($listener).AddArgument($root)
  $pool += [pscustomobject]@{ PS = $ps; Handle = $ps.BeginInvoke() }
}
while ($listener.IsListening) { Start-Sleep -Seconds 1 }
