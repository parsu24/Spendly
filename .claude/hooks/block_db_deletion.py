#!/usr/bin/env python3
"""PreToolUse guard: refuse any tool call that would delete or clobber spendly.db.

Reads the hook payload on stdin, prints a deny decision on a match, stays silent
otherwise. Read-only access to the database (sqlite3 SELECT, .schema, .dump) is
deliberately left alone.
"""

import json
import os
import re
import sys

DB_NAME = "spendly.db"

# Verbs that destroy or displace a file.
REMOVE = r"(?:rm|unlink|shred|srm|trash)"
# A verb counts only at the start of a command or after a shell separator.
START = r"(?:^|[;&|(]|\|\||&&)\s*(?:sudo\s+|env\s+\S+=\S+\s+)*"

DIRECT = [
    # rm spendly.db / sudo rm -f ./spendly.db
    re.compile(rf"{START}{REMOVE}\b[^;&|]*\b{re.escape(DB_NAME)}\b"),
    # mv spendly.db elsewhere (moving it away is a deletion) / mv x spendly.db
    re.compile(rf"{START}mv\b[^;&|]*\b{re.escape(DB_NAME)}\b"),
    # truncate -s0 spendly.db
    re.compile(rf"{START}truncate\b[^;&|]*\b{re.escape(DB_NAME)}\b"),
    # > spendly.db  (truncating redirect, including `: > spendly.db`)
    re.compile(rf">\s*(?:\./)?{re.escape(DB_NAME)}\b"),
    # find ... -delete / -exec rm, aimed at the db
    re.compile(rf"\bfind\b[^;&|]*{re.escape(DB_NAME)}[^;&|]*(?:-delete|-exec\s+{REMOVE})"),
]

# cp/dd/install only destroy the database when it is the *destination*.
# `cp spendly.db backup.db` is a backup and stays allowed.
COPY_SEGMENT = re.compile(rf"{START}(?:cp|install|dd)\b([^;&|]*)")

# Project root: .claude/hooks/<this file> -> three levels up.
PROJECT_ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
ROOT_TARGET = rf"\.|\*|\./\*?|{re.escape(PROJECT_ROOT)}/?"

# Sweeping removals that would take the database along with everything else.
SWEEP = [
    re.compile(rf"{START}{REMOVE}\b[^;&|]*(?:\*\.db|spendly\.\*)"),
    # rm -rf . | rm -rf * | rm -rf ./ | rm -rf <project root>
    re.compile(rf"{START}{REMOVE}\s+(?:-\S+\s+)*(?:{ROOT_TARGET})\s*(?:$|[;&|])"),
    # git clean wipes untracked files, and spendly.db is gitignored
    re.compile(r"\bgit\s+clean\b[^;&|]*-\S*[xX]"),
]


def deny(reason):
    """Emit a PreToolUse deny decision and stop."""
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    sys.exit(0)


def main():
    """Inspect the hook payload on stdin; deny anything that would destroy the DB."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    if tool in ("Write", "Edit", "NotebookEdit"):
        if os.path.basename(str(tool_input.get("file_path", ""))) == DB_NAME:
            deny(
                f"Blocked: {DB_NAME} is the SQLite database file and must not be written "
                f"or overwritten directly. Recreate it with database/db.py "
                f"(init_db/seed_db) or change data with a sqlite3 query."
            )
        return

    if tool == "Bash":
        cmd = str(tool_input.get("command", ""))
        clobbering_copy = any(
            os.path.basename(m.group(1).split()[-1].strip("\"'")) == DB_NAME
            for m in COPY_SEGMENT.finditer(cmd)
            if m.group(1).split()
        )
        if clobbering_copy or any(p.search(cmd) for p in DIRECT):
            deny(
                f"Blocked: this command would delete, move, or overwrite {DB_NAME}. "
                f"Reads (sqlite3 SELECT, .schema, .dump) are fine; recreate the database "
                f"with database/db.py instead of removing the file."
            )
        if any(p.search(cmd) for p in SWEEP):
            deny(
                f"Blocked: this removal pattern would sweep up {DB_NAME}. "
                f"Delete specific files by name instead."
            )


if __name__ == "__main__":
    main()
