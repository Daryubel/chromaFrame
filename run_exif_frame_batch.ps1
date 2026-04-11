param(
    [Parameter(Mandatory = $true)]
    [string]$InputFolder,

    [Parameter(Mandatory = $true)]
    [string]$Title,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [string]$PythonExecutable = "python",
    [string]$ScriptPath = "./exif_frame.py",
    [switch]$Recurse
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $InputFolder -PathType Container)) {
    throw "Input folder not found: $InputFolder"
}

if (-not (Test-Path -LiteralPath $ScriptPath -PathType Leaf)) {
    throw "Python script not found: $ScriptPath"
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$files = if ($Recurse) {
    Get-ChildItem -LiteralPath $InputFolder -File -Recurse | Where-Object { $_.Extension -match '^\.(jpg|jpeg)$' }
} else {
    Get-ChildItem -LiteralPath $InputFolder -File | Where-Object { $_.Extension -match '^\.(jpg|jpeg)$' }
}

if (-not $files -or $files.Count -eq 0) {
    Write-Warning "No JPG/JPEG files found in: $InputFolder"
    exit 0
}

foreach ($file in $files) {
    if ($Recurse) {
        $relativePath = [System.IO.Path]::GetRelativePath((Resolve-Path $InputFolder), $file.FullName)
        $relativeDir = [System.IO.Path]::GetDirectoryName($relativePath)
        $targetDir = if ([string]::IsNullOrEmpty($relativeDir)) { $OutputDirectory } else { Join-Path $OutputDirectory $relativeDir }
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        $outputPath = Join-Path $targetDir ("Framed_{0}.jpg" -f $file.BaseName)
    } else {
        $outputPath = Join-Path $OutputDirectory ("Framed_{0}.jpg" -f $file.BaseName)
    }

    Write-Host "Processing $($file.FullName) -> $outputPath"

    & $PythonExecutable $ScriptPath $file.FullName $outputPath --title $Title
    if ($LASTEXITCODE -ne 0) {
        throw "Failed while processing file: $($file.FullName)"
    }
}

Write-Host "Done. Processed $($files.Count) file(s)."
