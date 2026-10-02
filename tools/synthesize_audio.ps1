param(
    [Parameter(Mandatory=$true)][string]$CatalogPath,
    [Parameter(Mandatory=$true)][string]$AudioPath,
    [string]$Voice = '',
    [string]$RosterPath = ''
)
# Generate exactly the clips generate_catalog.clips() would ship for the
# current roster: pitches and locations only when an enrolled audio unit also
# receives pitch calls, and a play clip only when the play's resolved targets
# include an enrolled audio unit. Play clips with no audio audience (for
# example SEE DOWN/SEE UP when center field is the only target) are not
# generated.
$ErrorActionPreference = 'Stop'
if (-not $RosterPath) {
    $RosterPath = Join-Path (Split-Path -Parent $CatalogPath) 'roster.json'
}
$dictionary = Get-Content -LiteralPath $CatalogPath -Raw | ConvertFrom-Json
$roster = Get-Content -LiteralPath $RosterPath -Raw | ConvertFrom-Json
$groups = @{
    battery = @('pitcher', 'catcher')
    infield = @('first', 'second', 'third', 'shortstop')
    outfield = @('left', 'center', 'right')
    all = @('pitcher', 'catcher', 'first', 'second', 'third', 'shortstop', 'left', 'center', 'right')
}
$enrolled = @($roster.units | Where-Object { $_.enrolled })
$audioKeys = @($enrolled | Where-Object { $_.audio } | ForEach-Object { [string]$_.key })
$pitchKeys = @($enrolled | Where-Object { $_.pitches } | ForEach-Object { [string]$_.key })

function Test-PitchAudio {
    foreach ($key in $pitchKeys) {
        if ($audioKeys -contains $key) { return $true }
    }
    return $false
}

function Test-PlayAudio($play) {
    $audience = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($target in $play.targets) {
        if ($groups.ContainsKey($target)) {
            foreach ($key in $groups[$target]) { [void]$audience.Add($key) }
        } else {
            [void]$audience.Add([string]$target)
        }
    }
    foreach ($key in $audioKeys) {
        if ($audience.Contains($key)) { return $true }
    }
    return $false
}

Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    if ($Voice) { $speaker.SelectVoice($Voice) }
    $speaker.Rate = 0
    $speaker.Volume = 80
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    if (Test-PitchAudio) {
        foreach ($pitch in $dictionary.pitches) {
            $outputPath = Join-Path $AudioPath ('p{0:D2}.wav' -f [int]$pitch.key)
            $speaker.SetOutputToWaveFile($outputPath, $format)
            $speaker.Speak([string]$pitch.speech)
            $speaker.SetOutputToNull()
        }
        $locationIndex = 0
        foreach ($location in $dictionary.locations) {
            $locationIndex++
            $outputPath = Join-Path $AudioPath ('l{0}.wav' -f $locationIndex)
            $speaker.SetOutputToWaveFile($outputPath, $format)
            $speaker.Speak([string]$location.speech)
            $speaker.SetOutputToNull()
        }
    }
    foreach ($play in $dictionary.plays) {
        if (-not (Test-PlayAudio $play)) { continue }
        $outputPath = Join-Path $AudioPath ('d{0:D2}.wav' -f [int]$play.key)
        $speaker.SetOutputToWaveFile($outputPath, $format)
        $speaker.Speak([string]$play.speech)
        $speaker.SetOutputToNull()
    }
} finally { $speaker.Dispose() }
