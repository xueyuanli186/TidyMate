<#
.SYNOPSIS
    Creates a throw-away "drill sandbox" for TidyMate development and testing.

.DESCRIPTION
    Builds a fresh directory tree under %TEMP% that reproduces every condition the
    organiser has to survive: nested folders, many extensions, a read-only file, a
    system-flagged file, a hidden file, a file name close to the NTFS limit, a path
    longer than MAX_PATH, a directory junction, a file symbolic link (with a hard-link
    fallback), an NTFS alternate data stream, a zero byte file, unicode and space-laden
    names, duplicate basenames, and a fake journal database.

    SAFETY CONTRACT
      * NEVER deletes, moves or overwrites anything.
      * Refuses to run when -Root already exists. Choose a new path or delete the old
        sandbox yourself, deliberately.
      * Refuses to create anything under Windows\, Program Files\, or a drive root.
      * Every payload is fake text; no real user data is read or copied.

.PARAMETER Root
    Absolute path to create. Defaults to %TEMP%\tidymate-sandbox-<timestamp>.

.EXAMPLE
    pwsh -File scripts/make-sandbox.ps1

.EXAMPLE
    pwsh -File scripts/make-sandbox.ps1 -Root D:\drills\stage1
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Root = (Join-Path $env:TEMP ('tidymate-sandbox-' + (Get-Date -Format 'yyyyMMdd-HHmmss')))
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:Entries = [System.Collections.Generic.List[object]]::new()
$script:Notes = [System.Collections.Generic.List[string]]::new()
$script:RootPath = ''

function Get-ExtendedPath {
    <# Prefix a fully qualified path with the \\?\ extended-length marker. #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Path)
    if ($Path.StartsWith('\\?\')) { return $Path }
    return '\\?\' + $Path
}

function Assert-SafeSandboxRoot {
    <# Validate the requested root before creating anything. #>
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Candidate)

    if ([string]::IsNullOrWhiteSpace($Candidate)) { throw 'Root must not be empty.' }
    if ($Candidate.StartsWith('\\?\')) {
        throw 'Pass a normal path; this script adds the \\?\ prefix itself.'
    }

    $full = [System.IO.Path]::GetFullPath($Candidate)
    if ([System.IO.Path]::GetPathRoot($full) -eq $full) {
        throw "Refusing to use a drive root: $full"
    }

    $protected = @($env:SystemRoot, ${env:ProgramFiles}, ${env:ProgramFiles(x86)}) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    foreach ($prefix in $protected) {
        $prefixFull = [System.IO.Path]::GetFullPath($prefix).TrimEnd('\') + '\'
        $fullDir = $full.TrimEnd('\') + '\'
        if ($fullDir.StartsWith($prefixFull, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to create a sandbox under a protected location: $full"
        }
    }

    if (Test-Path -LiteralPath $full) {
        throw "Already exists: $full - this script never overwrites or deletes. Pass a new -Root."
    }
    return $full
}

function Add-SandboxEntry {
    <# Record one created item for the manifest. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [Parameter(Mandatory = $true)][string]$Kind,
        [long]$Bytes = 0,
        [string]$Note = ''
    )
    $script:Entries.Add([pscustomobject]@{
            Path  = $RelativePath
            Kind  = $Kind
            Bytes = $Bytes
            Note  = $Note
        })
}

function New-SandboxFile {
    <# Write one fake payload file and record it. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [string]$Content = '',
        [string]$Note = ''
    )

    $full = Join-Path -Path $script:RootPath -ChildPath $RelativePath
    $parent = [System.IO.Path]::GetDirectoryName($full)
    if (-not [System.IO.Directory]::Exists($parent)) {
        [System.IO.Directory]::CreateDirectory((Get-ExtendedPath $parent)) | Out-Null
    }
    [System.IO.File]::WriteAllText((Get-ExtendedPath $full), $Content)
    Add-SandboxEntry -RelativePath $RelativePath -Kind 'file' `
        -Bytes ([System.Text.Encoding]::UTF8.GetByteCount($Content)) -Note $Note
    return $full
}

function New-SandboxDirectory {
    <# Create one directory and record it. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RelativePath,
        [string]$Note = ''
    )
    $full = Join-Path -Path $script:RootPath -ChildPath $RelativePath
    [System.IO.Directory]::CreateDirectory((Get-ExtendedPath $full)) | Out-Null
    Add-SandboxEntry -RelativePath $RelativePath -Kind 'dir' -Note $Note
    return $full
}

# ---------------------------------------------------------------------------
# 0. validate + create the root
# ---------------------------------------------------------------------------
$script:RootPath = Assert-SafeSandboxRoot -Candidate $Root
[System.IO.Directory]::CreateDirectory((Get-ExtendedPath $script:RootPath)) | Out-Null
$createdAt = (Get-Date).ToString('o')
Write-Output "creating sandbox: $script:RootPath"

# ---------------------------------------------------------------------------
# 1. ordinary files, one per extension the rules engine is likely to care about
# ---------------------------------------------------------------------------
# This file is deliberately pure ASCII: Windows PowerShell 5.1 reads a BOM-less .ps1 in
# the system ANSI code page, and a single UTF-8 CJK literal is enough to mis-align the
# parser and break the whole script. Non-ASCII names are therefore built from code points.
$cjkFileName = (-join ([char[]](0x6587, 0x4EF6))) + '-' + `
    (-join ([char[]](0x4E2D, 0x6587, 0x540D))) + '.txt'          # CJK name, see tests
$cjkDirectoryName = -join ([char[]](0x5B50, 0x76EE, 0x5F55, 0x20, 0x5E26, 0x7A7A, 0x683C))

$samples = [ordered]@{
    'notes.txt'          = 'plain text payload'
    'report.docx'        = 'fake docx payload (not a real OOXML package)'
    'sheet.xlsx'         = 'fake xlsx payload'
    'deck.pptx'          = 'fake pptx payload'
    'manual.pdf'         = 'fake pdf payload'
    'photo.jpg'          = 'fake jpeg payload'
    'clip.mp4'           = 'fake mp4 payload'
    'song.mp3'           = 'fake mp3 payload'
    'archive.zip'        = 'fake zip payload'
    'bundle.tar.gz'      = 'fake tarball payload'
    'data.csv'           = "col_a,col_b`r`n1,2"
    'code.json'          = '{"a": 1}'
    'tool.py'            = 'print("payload")'
    'page.html'          = '<html><body>payload</body></html>'
    'UPPER.TXT'          = 'upper case extension payload'
    'README'             = 'no extension payload'
    '.dotfile'           = 'dot file payload'
    'file with spaces.txt' = 'name with spaces payload'
}
$samples[$cjkFileName] = 'unicode name payload'
foreach ($name in $samples.Keys) {
    New-SandboxFile -RelativePath (Join-Path 'inbox' $name) -Content $samples[$name] | Out-Null
}

# ---------------------------------------------------------------------------
# 2. nesting, including the same basename in two places (conflict drills)
# ---------------------------------------------------------------------------
New-SandboxFile -RelativePath (Join-Path 'inbox\2024\01\15' 'deep.txt') -Content 'nested by year/month/day' | Out-Null
New-SandboxFile -RelativePath (Join-Path 'inbox\2024\02\29' 'leap.txt') -Content 'leap day folder' | Out-Null
New-SandboxFile -RelativePath 'inbox\keep\photo.jpg' -Content 'same basename, folder A' -Note 'duplicate basename A' | Out-Null
New-SandboxFile -RelativePath 'inbox\tmp\photo.jpg' -Content 'same basename, folder B' -Note 'duplicate basename B' | Out-Null
New-SandboxFile -RelativePath (Join-Path ('inbox\' + $cjkDirectoryName) 'readme.txt') -Content 'unicode + space directory' | Out-Null
New-SandboxDirectory -RelativePath 'empty-dir' -Note 'empty directory' | Out-Null

# ---------------------------------------------------------------------------
# 3. zero byte file
# ---------------------------------------------------------------------------
$zeroByte = Join-Path $script:RootPath 'inbox\zero-byte.bin'
[System.IO.File]::WriteAllBytes((Get-ExtendedPath $zeroByte), [byte[]]::new(0))
Add-SandboxEntry -RelativePath 'inbox\zero-byte.bin' -Kind 'file' -Bytes 0 -Note 'zero byte file'

# ---------------------------------------------------------------------------
# 4. attributes: read-only, system, hidden (iron rule 8)
# ---------------------------------------------------------------------------
$readOnly = New-SandboxFile -RelativePath 'inbox\locked-readonly.txt' -Content 'read-only payload' `
    -Note 'FILE_ATTRIBUTE_READONLY'
[System.IO.File]::SetAttributes((Get-ExtendedPath $readOnly), [System.IO.FileAttributes]::ReadOnly)

$systemFlagged = New-SandboxFile -RelativePath 'inbox\system-flagged.dat' -Content 'system attribute payload' `
    -Note 'FILE_ATTRIBUTE_SYSTEM'
[System.IO.File]::SetAttributes((Get-ExtendedPath $systemFlagged), [System.IO.FileAttributes]::System)

$hiddenAttr = New-SandboxFile -RelativePath 'inbox\hidden-attribute.txt' -Content 'hidden attribute payload' `
    -Note 'FILE_ATTRIBUTE_HIDDEN'
[System.IO.File]::SetAttributes((Get-ExtendedPath $hiddenAttr), [System.IO.FileAttributes]::Hidden)

# ---------------------------------------------------------------------------
# 5. NTFS alternate data stream
# ---------------------------------------------------------------------------
$adsFile = New-SandboxFile -RelativePath 'inbox\with-alternate-stream.txt' -Content 'primary stream payload' `
    -Note 'has Zone.Identifier ADS'
Set-Content -LiteralPath $adsFile -Stream 'Zone.Identifier' -Value '[ZoneTransfer]', 'ZoneId=3'
$streamCheck = Get-Item -LiteralPath $adsFile -Stream 'Zone.Identifier'
if ($null -eq $streamCheck) { throw "sandbox bug: ADS was not created on $adsFile" }

# ---------------------------------------------------------------------------
# 6. long file name (single component, still under MAX_PATH) and long path (> 260)
# ---------------------------------------------------------------------------
$longComponent = 'longname-' + ('n' * 180) + '.txt'
if ($longComponent.Length -gt 255) { throw "sandbox bug: component too long ($($longComponent.Length))" }
$longNameFile = New-SandboxFile -RelativePath (Join-Path 'inbox' $longComponent) `
    -Content 'long component payload' -Note "filename length $($longComponent.Length)"
if ($longNameFile.Length -ge 260) {
    $script:Notes.Add("long filename path is $($longNameFile.Length) chars (already over MAX_PATH)")
}

$segments = @('longpath')
foreach ($index in 1..6) { $segments += ('segment-' + ('L' * 30) + ('0' + $index)) }
$deepDir = Join-Path $script:RootPath ($segments -join '\')
[System.IO.Directory]::CreateDirectory((Get-ExtendedPath $deepDir)) | Out-Null
$deepFile = Join-Path $deepDir 'deep-payload.txt'
[System.IO.File]::WriteAllText((Get-ExtendedPath $deepFile), 'long path payload')
if ($deepFile.Length -le 260) { throw "sandbox bug: expected > 260 chars, got $($deepFile.Length)" }
$serverRelativeLength = $deepFile.Length - $script:RootPath.Length
Add-SandboxEntry -RelativePath ($deepFile.Substring($script:RootPath.Length + 1)) -Kind 'file' `
    -Bytes 16 -Note "long path: $($deepFile.Length) chars, $serverRelativeLength relative"

# ---------------------------------------------------------------------------
# 7. links: one directory junction, one file link (symlink, else hardlink fallback)
# ---------------------------------------------------------------------------
$junctionPath = Join-Path $script:RootPath 'links\junction-to-inbox'
New-Item -ItemType Junction -Path $junctionPath -Target (Join-Path $script:RootPath 'inbox') `
    -ErrorAction Stop | Out-Null
Add-SandboxEntry -RelativePath 'links\junction-to-inbox' -Kind 'junction' -Note 'directory junction -> inbox'

$symlinkPath = Join-Path $script:RootPath 'links\symlink-to-notes.txt'
$symlinkTarget = Join-Path $script:RootPath 'inbox\notes.txt'
$linkKind = ''
try {
    New-Item -ItemType SymbolicLink -Path $symlinkPath -Target $symlinkTarget -ErrorAction Stop | Out-Null
    $linkKind = 'symlink'
}
catch {
    New-Item -ItemType HardLink -Path $symlinkPath -Target $symlinkTarget -ErrorAction Stop | Out-Null
    $linkKind = 'hardlink (fallback: no symlink privilege / Developer Mode off)'
    $script:Notes.Add('FILE SYMLINK NOT CREATED - fell back to a hard link.')
    $script:Notes.Add('Enable Developer Mode or run elevated to drill real symlinks.')
}
Add-SandboxEntry -RelativePath 'links\symlink-to-notes.txt' -Kind 'link' -Note $linkKind

# ---------------------------------------------------------------------------
# 8. a fake journal database (must stay gitignored, never committed)
# ---------------------------------------------------------------------------
New-SandboxFile -RelativePath 'tidymate-journal.db' -Content 'fake sqlite journal placeholder' `
    -Note 'fake *.db file - proves .gitignore covers it' | Out-Null

# ---------------------------------------------------------------------------
# 9. manifest: written into the sandbox and printed to stdout
# ---------------------------------------------------------------------------
$fileEntries = @($script:Entries | Where-Object { $_.Kind -eq 'file' })
if ($fileEntries.Count -lt 20) {
    throw "sandbox bug: only $($fileEntries.Count) files recorded, expected at least 20"
}

$byExtension = $fileEntries |
    Group-Object {
        $extension = [System.IO.Path]::GetExtension($_.Path)
        if ([string]::IsNullOrEmpty($extension)) { '(none)' } else { $extension.ToLowerInvariant() }
    } |
    Sort-Object -Property Name

$manifest = [System.Collections.Generic.List[string]]::new()
$manifest.Add('TidyMate drill sandbox manifest')
$manifest.Add("root      : $script:RootPath")
$manifest.Add("created   : $createdAt")
$manifest.Add('generator : scripts/make-sandbox.ps1 (stage 0)')
$manifest.Add("entries   : $($script:Entries.Count) ($($fileEntries.Count) files)")
$manifest.Add('')
$manifest.Add('PATH | KIND | BYTES | NOTE')
foreach ($entry in $script:Entries) {
    $manifest.Add(('{0} | {1} | {2} | {3}' -f $entry.Path, $entry.Kind, $entry.Bytes, $entry.Note))
}
$manifest.Add('')
$manifest.Add('EXTENSIONS')
foreach ($group in $byExtension) {
    $manifest.Add(('{0} = {1}' -f $group.Name, $group.Count))
}
$manifest.Add('')
$manifest.Add('NOTES')
if ($script:Notes.Count -eq 0) { $manifest.Add('none') }
foreach ($note in $script:Notes) { $manifest.Add($note) }
$manifest.Add('')
$manifest.Add('This directory is disposable. Delete it yourself when you are done')
$manifest.Add('(Explorer, or your own command line - this script will not do it for you).')

$manifestPath = Join-Path $script:RootPath 'sandbox-manifest.txt'
[string[]]$manifestLines = $manifest.ToArray()
[System.IO.File]::WriteAllLines((Get-ExtendedPath $manifestPath), $manifestLines)

Write-Output ''
Write-Output '=== entries ==='
foreach ($line in $manifest) { Write-Output $line }
Write-Output ''
Write-Output 'Reminder: this is a drill directory. Never run stage tests against real user folders.'
Write-Output "SANDBOX_ROOT=$script:RootPath"
