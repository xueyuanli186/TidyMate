"""Single source of truth for the TidyMate version (stage 0 requirement 10).

Everything derives from this string:

* ``hatchling`` reads it through ``[tool.hatch.version] path`` in ``pyproject.toml``;
* the CLI ``--version`` output reads it;
* ``scripts/make_dist.py`` names the zip and the bundle directory with it;
* ``scripts/version.py --assert-tag`` refuses release tags that do not match it;
* the MSI product version (later stage) must be ``MAJOR.MINOR.PATCH`` built from it.

The value must stay a plain ``MAJOR.MINOR.PATCH`` triple of integers: WiX/MSI cannot
represent pre-release suffixes, and four-part versions break ``tag == vVERSION``.

The assignment below is parsed by regex, do not reformat it.
"""

from __future__ import annotations

__version__ = "0.1.0"
