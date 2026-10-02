param(
    [Parameter(Mandatory=$true)][string]$CatalogPath,
    [Parameter(Mandatory=$true)][string]$AudioPath,
    [string]$Voice = ''
)
$ErrorActionPreference = 'Stop'
$dictionary = Get-Content -LiteralPath $CatalogPath -Raw | ConvertFrom-Json
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    if ($Voice) { $speaker.SelectVoice($Voice) }
    $speaker.Rate = 0
    $speaker.Volume = 80
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    foreach ($pitch in $dictionary.pitches) {
        $outputPath = Join-Path $AudioPath ('p{0:D2}.wav' -f [int]$pitch.key)
        $speaker.SetOutputToWaveFile($outputPath, $format)
        $speaker.Speak([string]$pitch.speech)
        $speaker.SetOutputToNull()
    }
    foreach ($group in @(@{Prefix='h'; Words=@('Up','Middle','Down')}, @{Prefix='s'; Words=@('Inside','Middle','Away')})) {
        for ($index=0; $index -lt 3; $index++) {
            $outputPath = Join-Path $AudioPath ('{0}{1}.wav' -f $group.Prefix, ($index+1))
            $speaker.SetOutputToWaveFile($outputPath, $format)
            $speaker.Speak([string]$group.Words[$index])
            $speaker.SetOutputToNull()
        }
    }
} finally { $speaker.Dispose() }
