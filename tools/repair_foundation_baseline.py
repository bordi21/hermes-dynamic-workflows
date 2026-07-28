from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "hermes_dynamic_workflows" / "child" / "presets.py"

old = '''    for spec in list_agent_types(cwd=cwd):
        if spec.name == clean:
            return spec
    return None
'''
new = '''    folded = clean.casefold()
    for spec in list_agent_types(cwd=cwd):
        if spec.name.casefold() == folded:
            return spec
    return None
'''

text = PATH.read_text(encoding="utf-8")
if text.count(old) != 1:
    raise RuntimeError(f"expected one agent-type fallback block in {PATH}")
PATH.write_text(text.replace(old, new, 1), encoding="utf-8")
