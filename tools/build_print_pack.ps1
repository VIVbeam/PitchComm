<#
.SYNOPSIS
Rebuilds or verifies a PitchComm case print pack from cad/unbranded/exports.

.DESCRIPTION
Creates a repository-root zip:

  stl/            every STL except *_color.stl and fit_coupon.stl
  3mf/            grouped 3MF print files
  fit_coupon.stl  calibration coupon at the pack root
  README.md       cad/unbranded/README.md (print settings, assembly, wear)
  PART_COUNTS.txt per-style part counts and totals

The default full pack holds all three styles and lands at
PitchComm-cases-print-pack.zip (29 STLs, 6 3MFs). -Bench selects the pitcher
(receiver) and catcher (keypad) sets only: 21 parts plus the coupon, which is
the bench (coach + catcher + pitcher) print list, and lands at
PitchComm-cases-bench-pack.zip (21 STLs, 4 3MFs).

The archive is written with System.IO.Compression and then reopened and
checked entry by entry (exact names, counts, sizes, no colour STLs, portable
paths). -Verify skips the build and checks the existing zip in the selected
mode. The exit code is 1 on any mismatch.

.EXAMPLE
tools\build_print_pack.ps1
Rebuilds the full print pack at the repository root.

.EXAMPLE
tools\build_print_pack.ps1 -Bench
Rebuilds the bench print pack (pitcher and catcher, 21 parts plus coupon).

.EXAMPLE
tools\build_print_pack.ps1 -Bench -Verify
Verifies the existing bench pack without rebuilding it.
#>
param(
    [string]$Output = '',
    [switch]$Bench,
    [switch]$Verify
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$mode = if ($Bench) { 'bench' } else { 'full' }
if (-not $Output) {
    $Output = if ($Bench) { Join-Path $root 'PitchComm-cases-bench-pack.zip' } else { Join-Path $root 'PitchComm-cases-print-pack.zip' }
}
$exports = Join-Path $root 'cad/unbranded/exports'
$packReadme = Join-Path $root 'cad/unbranded/README.md'
$coupon = Join-Path $exports 'fit_coupon.stl'

Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.IO.Compression

if (-not (Test-Path -LiteralPath $exports -PathType Container)) { throw "Export folder not found: $exports" }
if (-not (Test-Path -LiteralPath $packReadme -PathType Leaf)) { throw "Pack README not found: $packReadme" }
if (-not (Test-Path -LiteralPath $coupon -PathType Leaf)) { throw "Fit coupon not found: $coupon" }

# --- collect the printable files --------------------------------------------
$allStl = @(Get-ChildItem -LiteralPath $exports -File -Filter '*.stl' |
    Where-Object { $_.Name -notlike '*_color.stl' -and $_.Name -ne 'fit_coupon.stl' } |
    Sort-Object Name)
$allThreeMf = @(Get-ChildItem -LiteralPath $exports -File -Filter '*.3mf' | Sort-Object Name)
if (-not $allStl.Count) { throw "No printable STLs found in $exports" }
if (-not $allThreeMf.Count) { throw "No 3MF files found in $exports" }

# Styles are the three case families. The fielder can wear either carrier;
# wrist_belt_carrier.stl is shipped as the optional alternative, so it is not
# part of the 7-part fielder set in cad/unbranded/README.md. The bench pack
# selects the pitcher and catcher styles only.
$styles = [ordered]@{
    'Pitcher (receiver)' = @{ Prefix = 'receiver_'; Optional = '' }
    'Catcher (keypad)'   = @{ Prefix = 'keypad_';   Optional = '' }
    'Fielder (wrist)'    = @{ Prefix = 'wrist_';    Optional = 'wrist_belt_carrier.stl' }
}
$assigned = @{}
foreach ($style in $styles.Keys) { $assigned[$style] = New-Object 'System.Collections.Generic.List[object]' }
foreach ($file in $allStl) {
    $matched = $false
    foreach ($style in $styles.Keys) {
        if ($file.Name.StartsWith($styles[$style].Prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $assigned[$style].Add($file)
            $matched = $true
            break
        }
    }
    if (-not $matched) {
        throw ('Unrecognized STL style: {0}. Add its prefix to $styles in tools/build_print_pack.ps1.' -f $file.Name)
    }
}

$activeStyles = if ($Bench) { @('Pitcher (receiver)', 'Catcher (keypad)') } else { @($styles.Keys) }
$activePrefixes = @($activeStyles | ForEach-Object { $styles[$_].Prefix })

function Test-ActiveName {
    param([string]$Name, [string[]]$Prefixes)
    foreach ($prefix in $Prefixes) {
        if ($Name.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

$stl = @()
foreach ($style in $activeStyles) { $stl += @($assigned[$style] | ForEach-Object { $_ }) }
$stl = @($stl | Sort-Object Name)
$threeMf = @($allThreeMf | Where-Object { Test-ActiveName $_.Name $activePrefixes } | Sort-Object Name)
$expectedThreeMf = if ($Bench) { 4 } else { 6 }
if ($threeMf.Count -ne $expectedThreeMf) {
    throw ("Expected {0} 3MF files for the {1} pack in {2}; found {3}" -f $expectedThreeMf, $mode, $exports, $threeMf.Count)
}

$required = @{}
$optionalParts = New-Object 'System.Collections.Generic.List[object]'
foreach ($style in $activeStyles) {
    $optionalName = $styles[$style].Optional
    $required[$style] = @($assigned[$style] | Where-Object { $_.Name -ne $optionalName })
    foreach ($file in $assigned[$style]) {
        if ($file.Name -eq $optionalName) { $optionalParts.Add($file) }
    }
    if ($required[$style].Count -lt 6) {
        throw ("Style '{0}' has only {1} required parts; expected at least 6. Check {2}." -f
            $style, $required[$style].Count, $exports)
    }
}

$pitcherCount = $required['Pitcher (receiver)'].Count
$catcherCount = $required['Catcher (keypad)'].Count
$fielderCount = if ($activeStyles -contains 'Fielder (wrist)') { $required['Fielder (wrist)'].Count } else { 0 }
$teamTotal = $pitcherCount + $catcherCount + 2 * $fielderCount
$teamBothCarriers = $teamTotal + 2 * $optionalParts.Count
$benchTotal = $pitcherCount + $catcherCount

# --- expected entries and the sources for the size check ---------------------
$expectedEntries = New-Object 'System.Collections.Generic.List[string]'
$sourceMap = @{}
$expectedEntries.Add('README.md')
$sourceMap['README.md'] = $packReadme
$expectedEntries.Add('PART_COUNTS.txt')
$expectedEntries.Add('fit_coupon.stl')
$sourceMap['fit_coupon.stl'] = $coupon
foreach ($file in $stl) {
    $expectedEntries.Add('stl/' + $file.Name)
    $sourceMap['stl/' + $file.Name] = $file.FullName
}
foreach ($file in $threeMf) {
    $expectedEntries.Add('3mf/' + $file.Name)
    $sourceMap['3mf/' + $file.Name] = $file.FullName
}

function Test-PackArchive {
    param([string]$Path, $Expected, $Sources)
    $problems = New-Object 'System.Collections.Generic.List[string]'
    $zip = [System.IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $actual = @($zip.Entries | ForEach-Object { $_.FullName })
        if ($actual.Count -ne $Expected.Count) {
            $problems.Add(('entry count is {0}; expected {1}' -f $actual.Count, $Expected.Count))
        }
        foreach ($name in $Expected) {
            if ($actual -notcontains $name) { $problems.Add('missing entry: ' + $name) }
        }
        foreach ($name in $actual) {
            if ($Expected -notcontains $name) { $problems.Add('unexpected entry: ' + $name) }
            if ($name.StartsWith('/') -or $name.Contains('\')) {
                $problems.Add('non-portable entry name: ' + $name)
            }
        }
        foreach ($entry in $zip.Entries) {
            if ($entry.Length -le 0) { $problems.Add('empty entry: ' + $entry.FullName) }
            if ($entry.FullName -like 'stl/*_color.stl') { $problems.Add('colour STL in the pack: ' + $entry.FullName) }
            if ($entry.FullName -eq 'stl/fit_coupon.stl') { $problems.Add('fit coupon must stay at the pack root') }
            if ($Sources.ContainsKey($entry.FullName)) {
                $size = (Get-Item -LiteralPath $Sources[$entry.FullName]).Length
                if ($entry.Length -ne $size) {
                    $problems.Add(('size mismatch for {0}: {1} in the zip, {2} on disk' -f $entry.FullName, $entry.Length, $size))
                }
            }
        }
    } finally {
        $zip.Dispose()
    }
    return ,$problems
}

# --- verify-only mode -------------------------------------------------------
if ($Verify) {
    if (-not (Test-Path -LiteralPath $Output -PathType Leaf)) {
        throw ("No pack to verify at {0}. Build it first with tools\build_print_pack.ps1{1}." -f
            $Output, $(if ($Bench) { ' -Bench' } else { '' }))
    }
    $problems = Test-PackArchive $Output $expectedEntries $sourceMap
    if ($problems.Count) {
        throw ("Print pack verification failed ({0} mode, {1}):`n  {2}" -f $mode, $Output, ($problems -join "`n  "))
    }
    Write-Host ("Print pack verified ({0} mode): {1}" -f $mode, $Output)
    Write-Host ("  entries: {0} ({1} stl, {2} 3mf, no *_color.stl, fit coupon at the root)" -f
        $expectedEntries.Count, $stl.Count, $threeMf.Count)
    if ($Bench) {
        Write-Host ("  bench: {0} parts plus the coupon (catcher {1}, pitcher {2})" -f
            $benchTotal, $catcherCount, $pitcherCount)
    } else {
        Write-Host ("  full team: {0} parts (pitcher 1 x {1}, catcher 1 x {2}, fielder 2 x {3})" -f
            $teamTotal, $pitcherCount, $catcherCount, $fielderCount)
    }
    Write-Host 'Print pack verified with System.IO.Compression.'
    exit 0
}

# --- PART_COUNTS.txt --------------------------------------------------------
$textLines = New-Object 'System.Collections.Generic.List[string]'
if ($Bench) {
    $textLines.Add('PitchComm cases bench print pack: part counts')
    $textLines.Add('Generated by tools/build_print_pack.ps1 -Bench from cad/unbranded/exports.')
} else {
    $textLines.Add('PitchComm cases print pack: part counts')
    $textLines.Add('Generated by tools/build_print_pack.ps1 from cad/unbranded/exports.')
}
$textLines.Add('')
$textLines.Add('Pack contents')
if ($Bench) {
    $textLines.Add(('  stl/            {0} STL files (pitcher and catcher parts; no *_color.stl and no fit coupon)' -f $stl.Count))
    $textLines.Add(('  3mf/            {0} 3MF files (receiver and keypad grouped prints)' -f $threeMf.Count))
} else {
    $textLines.Add(('  stl/            {0} STL files (unit parts; no *_color.stl and no fit coupon)' -f $stl.Count))
    $textLines.Add(('  3mf/            {0} 3MF files (grouped colour prints)' -f $threeMf.Count))
}
$textLines.Add('  fit_coupon.stl  1 STL at the pack root (calibration; print first)')
$textLines.Add('  README.md       print settings, assembly and wear notes')
$textLines.Add('')
$textLines.Add('Parts per style (one pod per player)')
foreach ($style in $activeStyles) {
    $list = (@($required[$style] | ForEach-Object { [System.IO.Path]::GetFileNameWithoutExtension($_.Name) }) -join ', ')
    $textLines.Add(('  {0,-18} {1,2} parts: {2}' -f $style, $required[$style].Count, $list))
}
if (-not $Bench -and $optionalParts.Count) {
    $optList = (@($optionalParts | ForEach-Object { $_.Name }) -join ', ')
    $textLines.Add(('  {0,-18}     optional: {1}' -f '', $optList))
    $textLines.Add(('  {0,-18}               alternative carrier; not counted in the sets below' -f ''))
}
$textLines.Add('')
if ($Bench) {
    $textLines.Add('Bench: coach + catcher + pitcher')
    $textLines.Add('  Coach     no printed case (GUI console on a laptop)')
    $textLines.Add(('  Catcher   1 x {0,2} = {1,3}' -f $catcherCount, $catcherCount))
    $textLines.Add(('  Pitcher   1 x {0,2} = {1,3}' -f $pitcherCount, $pitcherCount))
    $textLines.Add(('  Total                {0,3} printed parts' -f $benchTotal))
} else {
    $textLines.Add('Full team: pitcher 1 set, catcher 1 set, fielder 2 sets')
    $textLines.Add(('  Pitcher   1 x {0,2} = {1,3}' -f $pitcherCount, $pitcherCount))
    $textLines.Add(('  Catcher   1 x {0,2} = {1,3}' -f $catcherCount, $catcherCount))
    $textLines.Add(('  Fielder   2 x {0,2} = {1,3}' -f $fielderCount, (2 * $fielderCount)))
    $textLines.Add(('  Total                {0,3} printed parts' -f $teamTotal))
    if ($optionalParts.Count) {
        $textLines.Add(('  With both fielder carrier options: {0} printed parts' -f $teamBothCarriers))
    }
    $textLines.Add('')
    $textLines.Add('Bench: coach + catcher + pitcher')
    $textLines.Add('  Coach     no printed case (GUI console on a laptop)')
    $textLines.Add(('  Catcher   1 x {0,2} = {1,3}' -f $catcherCount, $catcherCount))
    $textLines.Add(('  Pitcher   1 x {0,2} = {1,3}' -f $pitcherCount, $pitcherCount))
    $textLines.Add(('  Total                {0,3} printed parts' -f $benchTotal))
}
$textLines.Add('')
$textLines.Add('The fit coupon is calibration hardware, not a unit part; it is not counted above.')
$partCountsText = ($textLines -join "`n") + "`n"

# --- write the archive ------------------------------------------------------
$outDir = Split-Path -Parent $Output
if ($outDir -and -not (Test-Path -LiteralPath $outDir -PathType Container)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}
$temp = $Output + '.tmp'
if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force }

$archive = [System.IO.Compression.ZipFile]::Open($temp, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    function Add-FileEntry {
        param($Archive, [string]$EntryName, [string]$Path)
        $entry = $Archive.CreateEntry($EntryName, [System.IO.Compression.CompressionLevel]::Optimal)
        $entry.LastWriteTime = (Get-Item -LiteralPath $Path).LastWriteTime
        $input = [System.IO.File]::OpenRead($Path)
        try {
            $output = $entry.Open()
            try { $input.CopyTo($output) } finally { $output.Dispose() }
        } finally { $input.Dispose() }
    }
    function Add-TextEntry {
        param($Archive, [string]$EntryName, [string]$Text, [datetime]$Stamp)
        $entry = $Archive.CreateEntry($EntryName, [System.IO.Compression.CompressionLevel]::Optimal)
        $entry.LastWriteTime = $Stamp
        $bytes = [System.Text.Encoding]::ASCII.GetBytes($Text)
        $output = $entry.Open()
        try { $output.Write($bytes, 0, $bytes.Length) } finally { $output.Dispose() }
    }

    foreach ($file in $stl) { Add-FileEntry $archive ('stl/' + $file.Name) $file.FullName }
    foreach ($file in $threeMf) { Add-FileEntry $archive ('3mf/' + $file.Name) $file.FullName }
    Add-FileEntry $archive 'fit_coupon.stl' $coupon
    Add-FileEntry $archive 'README.md' $packReadme
    Add-TextEntry $archive 'PART_COUNTS.txt' $partCountsText (Get-Item -LiteralPath $packReadme).LastWriteTime
} finally {
    $archive.Dispose()
}

$problems = Test-PackArchive $temp $expectedEntries $sourceMap
if ($problems.Count) {
    Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    throw ("Print pack verification failed:`n  " + ($problems -join "`n  "))
}
Move-Item -LiteralPath $temp -Destination $Output -Force

Write-Host ("Print pack ({0} mode): {1}" -f $mode, $Output)
Write-Host ("  entries: {0} ({1} stl, {2} 3mf, fit coupon, README.md, PART_COUNTS.txt)" -f
    $expectedEntries.Count, $stl.Count, $threeMf.Count)
if ($Bench) {
    Write-Host ("  bench: {0} parts plus the coupon (catcher {1}, pitcher {2})" -f
        $benchTotal, $catcherCount, $pitcherCount)
} else {
    Write-Host ("  full team: {0} parts (pitcher 1 x {1}, catcher 1 x {2}, fielder 2 x {3})" -f
        $teamTotal, $pitcherCount, $catcherCount, $fielderCount)
    Write-Host ("  bench: {0} parts (coach 0, catcher 1 x {1}, pitcher 1 x {2})" -f
        $benchTotal, $catcherCount, $pitcherCount)
}
Write-Host 'Print pack verified with System.IO.Compression.'
Write-Host ''
Write-Host $partCountsText.TrimEnd()
