#!/usr/bin/env python3
"""One-off: reorder the A-sections in pre-arch.md into A1..A6 order."""
import re
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "pre-arch.md"
text = p.read_text(encoding="utf-8")

# Split the A-section block: everything from "## A1" to the "# PART B"
start = text.index("## A1")
end = text.index("# PART B")
block = text[start:end]

# Section chunks start at "## A" headers
parts = re.split(r"(?=^## A\d)", block, flags=re.M)
header = parts[0]  # text before the first "## A" (should be empty)
sections = {}
for part in parts[1:]:
    m = re.match(r"## (A\d)", part)
    sections[m.group(1)] = part.rstrip() + "\n\n"

order = [f"A{i}" for i in range(1, 7)]
assert set(sections) == set(order), f"unexpected sections: {sections.keys()}"

rebuilt = header + "\n".join(sections[k] for k in order)
text = text[:start] + rebuilt + text[end:]
text = re.sub(r"\n{3,}", "\n\n", text)
p.write_text(text, encoding="utf-8")

final = p.read_text(encoding="utf-8")
print([l for l in final.splitlines() if l.startswith("## A")])
