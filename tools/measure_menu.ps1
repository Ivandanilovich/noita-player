param([string]$Path)
Add-Type -AssemblyName System.Drawing
$bmp = [System.Drawing.Bitmap]::FromFile($Path)
$w = $bmp.Width; $h = $bmp.Height
Write-Host "size: ${w}x${h}"
$rect = New-Object System.Drawing.Rectangle 0, 0, $w, $h
$data = $bmp.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::ReadOnly, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$bytes = New-Object byte[] ($data.Stride * $h)
[System.Runtime.InteropServices.Marshal]::Copy($data.Scan0, $bytes, 0, $bytes.Length) | Out-Null
$bmp.UnlockBits($data) | Out-Null
$bmp.Dispose()
$stride = $data.Stride
$x0 = [int]($w * 0.44); $x1 = [int]($w * 0.56)
$rowHits = New-Object int[] $h
for ($y = 0; $y -lt $h; $y++) {
  $hits = 0
  $off = $y * $stride
  for ($x = $x0; $x -lt $x1; $x += 2) {
    $i = $off + $x * 4
    $b = $bytes[$i]; $g = $bytes[$i+1]; $r = $bytes[$i+2]
    if ($r -gt 190 -and $g -gt 190 -and $b -gt 190) { $hits++ }
  }
  if ($hits -gt 4) { $rowHits[$y] = 1 }
}
$y = 0
while ($y -lt $h) {
  if ($rowHits[$y] -gt 0) {
    $start = $y
    while ($y -lt $h -and $rowHits[$y] -gt 0) { $y++ }
    $center = [int](($start + $y - 1) / 2)
    $minx = -1; $maxx = -1
    for ($xx = 0; $xx -lt $w; $xx++) {
      $i = $center * $stride + $xx * 4
      if ($bytes[$i+2] -gt 190 -and $bytes[$i+1] -gt 190 -and $bytes[$i] -gt 190) { if ($minx -lt 0) { $minx = $xx }; $maxx = $xx }
    }
    Write-Host ("row: y={0}  x=[{1}..{2}]  cx={3}" -f $center, $minx, $maxx, [int](($minx + $maxx) / 2))
  } else { $y++ }
}