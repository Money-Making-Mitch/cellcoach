#!/usr/bin/env python3
"""
Extract G.U.T.S. dialogue from conversations.json and write guts_corpus.txt.

Usage:
    python3 tests/extract_dialogue.py

Output:
    tests/guts_corpus.txt — one ## <conversation name> header per conversation
    with full human + assistant text underneath, so it can be read in slices.

Run from cell_coach/ directory:
    cd C:/Users/Admin/data_center/cell_coach
    python3 tests/extract_dialogue.py
"""
import json
import os
import sys

# conversations.json is supplied from the session uploads folder
CONVERSATIONS_PATHS = [
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..",
                 "AppData", "Roaming", "Claude", "local-agent-mode-sessions",
                 "d8ac086b-0c75-45c2-ab10-10a5b3ff2f53",
                 "be2a5b2f-e5ae-428a-adcd-6630dfdeff47",
                 "local_6f51d81c-4d64-40d6-99b2-f2b5132217be",
                 "uploads", "conversations.json"),
    # Fallback: path from spec
    os.path.join(os.path.dirname(__file__), "..", "conversations.json"),
    # Allow explicit path as first CLI arg
]
if len(sys.argv) > 1:
    CONVERSATIONS_PATHS.insert(0, sys.argv[1])

OUT_PATH = os.path.join(os.path.dirname(__file__), "guts_corpus.txt")

# Conversations most likely to contain G.U.T.S. exemplars
PRIORITY_NAMES = [
    "claude diamond",
    "g.u.t.s",
    "guts",
    "grant cardone",
    "cold call coach",
    "cold call",
]


def _text_from_message(msg):
    """Extract plain text from a chat message, falling back to content blocks."""
    t = (msg.get("text") or "").strip()
    if t:
        return t
    # Fall back to content[].text where type=="text"
    for block in (msg.get("content") or []):
        if isinstance(block, dict) and block.get("type") == "text":
            part = (block.get("text") or "").strip()
            if part:
                return part
    return ""


def _is_priority(name):
    lower = (name or "").lower()
    return any(kw in lower for kw in PRIORITY_NAMES)


def main():
    src = None
    for p in CONVERSATIONS_PATHS:
        p = os.path.normpath(os.path.expanduser(p))
        if os.path.exists(p):
            src = p
            break
    if not src:
        print("ERROR: conversations.json not found. Searched:")
        for p in CONVERSATIONS_PATHS:
            print(" ", os.path.normpath(p))
        sys.exit(1)

    print(f"Loading {src} ...")
    with open(src, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("ERROR: expected a list of conversation objects")
        sys.exit(1)

    print(f"Total conversations: {len(data)}")

    # Sort: priority conversations first
    priority = [c for c in data if _is_priority(c.get("name", ""))]
    others = [c for c in data if not _is_priority(c.get("name", ""))]
    ordered = priority + others

    lines = []
    for conv in ordered:
        name = conv.get("name") or "(unnamed)"
        messages = conv.get("chat_messages") or []
        msg_count = len(messages)
        is_pri = _is_priority(name)
        tag = " [PRIORITY]" if is_pri else ""
        print(f"  {name}{tag}: {msg_count} messages")
        lines.append(f"\n## {name}")
        lines.append(f"<!-- messages: {msg_count} -->")
        for msg in messages:
            sender = msg.get("sender", "unknown")
            text = _text_from_message(msg)
            if not text:
                continue
            # Trim very long messages (unlikely to be call exemplars)
            if len(text) > 8000:
                text = text[:8000] + "\n... [truncated]"
            lines.append(f"\n[{sender.upper()}]\n{text}")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\nWrote {OUT_PATH} ({os.path.getsize(OUT_PATH):,} bytes)")
    print("Priority conversations extracted first.")
    print("Read in slices with: Read(file_path=OUT_PATH, offset=N, limit=200)")


if __name__ == "__main__":
    main()
