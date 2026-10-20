"""``verify`` (M9): compare the journal with the file system, entry by entry.

This is the evidence tool for "all files were restored": it does not trust the log, it
stats every path the log claims. A mismatch is reported with the sequence number and a
machine-readable code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from tidymate_core.journal import Journal
from tidymate_core.safety import paths


@dataclass(frozen=True, slots=True)
class VerifyProblem:
    """One inconsistency between the journal and the disk."""

    seq: int
    code: str
    message: str

    def render(self) -> str:
        """Single line for the CLI."""
        return f"seq {self.seq}: [{self.code}] {self.message}"


def _display(path: str) -> str:
    return paths.from_extended(path)


def verify_batch(
    journal: Journal,
    batch_id: str,
    *,
    sample: int | None = None,
) -> list[VerifyProblem]:
    """Return every place where the file system disagrees with the journal."""
    problems: list[VerifyProblem] = []
    seen = 0
    for row in journal.operations(batch_id):
        if sample is not None and seen >= sample:
            break
        seen += 1
        seq = int(str(row["seq"]))
        state = str(row["state"])
        src = str(row["src"])
        dst = row.get("final_dst") or row.get("dst")
        dst_text = str(dst) if dst is not None else None

        if state == "ok":
            op = str(row["op"])
            if op == "trash":
                if os.path.exists(_display(src)):
                    problems.append(
                        VerifyProblem(seq, "trash_source_present", f"{src!r} should be recycled"),
                    )
                continue
            if dst_text is None:
                problems.append(VerifyProblem(seq, "no_destination", "ok row has no destination"))
                continue
            if not os.path.exists(_display(dst_text)):
                problems.append(
                    VerifyProblem(seq, "missing_after_apply", f"expected {dst_text!r} to exist"),
                )
                continue
            expected = int(str(row.get("size") or 0))
            actual = os.stat(_display(dst_text)).st_size
            if expected and actual != expected:
                problems.append(
                    VerifyProblem(
                        seq,
                        "size_mismatch",
                        f"{dst_text!r}: journal {expected}, disk {actual}",
                    ),
                )
        elif state == "undone":
            if not os.path.exists(_display(src)):
                problems.append(
                    VerifyProblem(seq, "not_restored", f"expected {src!r} to be restored"),
                )
        elif state == "undo_failed":
            if dst_text is not None and not os.path.exists(_display(dst_text)):
                problems.append(
                    VerifyProblem(
                        seq,
                        "undo_failed_and_missing",
                        f"undo failed and {dst_text!r} is gone; manual recovery needed",
                    ),
                )
        elif state in {"interrupted", "planned"}:
            problems.append(
                VerifyProblem(seq, "interrupted", "operation was interrupted; inspect manually"),
            )
    return problems
