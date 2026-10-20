"""Restore files from the Windows recycle bin (M8).

``send2trash`` can put a file in the bin but cannot take it out again; the Shell exposes
that only through the recycle-bin folder's verbs. This module drives the Shell from
PowerShell (already present on every supported Windows) and reports honestly:

* ``RESTORED`` - the original path exists again;
* ``NOT_FOUND`` - no matching item (the bin was emptied or the item was purged);
* ``NO_VERB`` / ``FAILED`` - the Shell refused.

Matching uses ``System.Recycle.DeletedFrom`` plus the file name, so a file with the same
name deleted from another folder is never restored by mistake.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$original = $env:TIDYMATE_ORIGINAL
$parent = [System.IO.Path]::GetDirectoryName($original)
$name = [System.IO.Path]::GetFileName($original)
$shell = New-Object -ComObject Shell.Application
$bin = $shell.Namespace(10)
$found = $null
foreach ($item in $bin.Items()) {
    try { $from = $item.ExtendedProperty('System.Recycle.DeletedFrom') } catch { $from = $null }
    if ($item.Name -eq $name -and $from -eq $parent) {
        $found = $item
        break
    }
}
if ($null -eq $found) { Write-Output 'NOT_FOUND'; exit 0 }
$verbs = $found.Verbs() | Where-Object { $_.Name -match '还原|Restore|复原' }
$verb = $verbs | Select-Object -First 1
if ($null -eq $verb) { Write-Output 'NO_VERB'; exit 0 }
$verb.DoIt()
Start-Sleep -Milliseconds 400
if (Test-Path -LiteralPath $original) { Write-Output 'RESTORED' } else { Write-Output 'FAILED' }
"""


def restore_to(original: str) -> tuple[bool, str]:
    """Ask the Shell to restore *original* from the recycle bin.

    Returns ``(restored, reason)``. Never raises for a Shell refusal; the caller records
    ``recycle_gone`` and prints the manual recovery hint.
    """
    if os.name != "nt":
        return False, "not_windows"
    powershell = shutil.which("powershell") or "powershell"
    environment = dict(os.environ, TIDYMATE_ORIGINAL=original)
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
            [powershell, "-NoProfile", "-NonInteractive", "-Command", _SCRIPT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            env=environment,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"shell_error: {exc}"
    output = (result.stdout or "").strip().splitlines()
    status = output[-1].strip() if output else "FAILED"
    return status == "RESTORED", status.lower()


def recycle_reference(original: str) -> str:
    """Return the JSON blob stored in ``operations.recycle_ref``."""
    return json.dumps(
        {
            "original": original,
            "parent": str(Path(original).parent),
            "name": Path(original).name,
        },
        ensure_ascii=False,
    )
