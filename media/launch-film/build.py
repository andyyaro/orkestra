"""Write the scene windows from sound/timing.json (made by sound/mix.py) into index.html.

    python3 -I build.py

Each scene host's data-start/data-duration, the terminal mount's, and the root duration come from the same numbers
the scenes read at runtime (window.TM in assets/timing.js), so the two can never drift apart.
"""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TM = json.loads((ROOT / "sound/timing.json").read_text())
HOSTS = {"s1-problem": "s1", "s2-meet": "s2", "s3-how": "s3", "s4-repair": "s4", "s5-proof": "s5", "s6-try": "s6", "s7-end": "s7"}
r = lambda x: f"{x:.3f}".rstrip("0").rstrip(".")

s = (ROOT / "index.html").read_text()
for host, key in HOSTS.items():
    a, b = TM[key]
    s, n = re.subn(rf'(<div id="{host}"[^>]*?data-start=")[^"]*(" data-duration=")[^"]*(")', rf"\g<1>{r(a)}\g<2>{r(b - a)}\g<3>", s)
    assert n == 1, host
t0, td = TM["term"]
s, n = re.subn(r'(<div id="code-terminal-run"[^>]*?data-start=")[^"]*("\s+data-duration=")[^"]*(")', rf"\g<1>{r(t0)}\g<2>{r(td)}\g<3>", s, flags=re.S)
assert n == 1, "terminal"
s, n = re.subn(r'(<div id="main"[^>]*?data-duration=")[^"]*(")', rf"\g<1>{r(TM['duration'])}\g<2>", s); assert n == 1
s, n = re.subn(r'(<audio id="soundtrack"[^>]*?data-duration=")[^"]*(")', rf"\g<1>{r(TM['duration'])}\g<2>", s); assert n == 1
if 'assets/timing.js' not in s:
    s = s.replace('<script src="assets/vo.js"></script>', '<script src="assets/vo.js"></script>\n    <script src="assets/timing.js"></script>')
(ROOT / "index.html").write_text(s)
print("index.html:", ", ".join(f"{k} {TM[k][0]}-{TM[k][1]}" for k in HOSTS.values()), f"| terminal {t0}+{td} | {TM['duration']} s")
