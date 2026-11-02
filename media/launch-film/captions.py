"""Write the narration as a captions file, renders/orkestra-v2-calm.en.vtt, from its word times in assets/vo.js.

    python3 -I captions.py

The film has no burned-in subtitles: its headlines carry the story with the sound off. This file is for players and
the watch page. It was added with the film's source, after the render, and changes nothing in the picture.

Each cue is the next words of one narration line, at most 2 lines of 42 characters, shown from 0.08 s before its
first word to 0.30 s after its last (and never into the next cue). The text is the script as written
(narration/lines.json), with 557 and 60 in figures as they are on screen. The word counts are those of the voiced
take in assets/vo.js, so a re-voiced line that changes its count stops the build here.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
vo_js = (ROOT / "assets/vo.js").read_text()
VO = json.loads(vo_js[vo_js.index("{"): vo_js.rindex("}") + 1])

CUES = [  # (line, words of the voiced take in this cue, caption)
    ("v01", 5, "You already use coding agents."),
    ("v02", 4, "Claude Code. Codex. Antigravity."),
    ("v03", 6, "One at a time is slow."),
    ("v04", 5, "All at once is chaos."),
    ("v05", 2, "Meet Orkestra."),
    ("v06", 8, "Many coding agents. One repo.\nNothing lands unreviewed."),
    ("v07", 5, "A director plans the work,"),
    ("v07", 9, "and every task runs\nin its own Git worktree."),
    ("v08", 5, "Your tests are the referee."),
    ("v09", 10, "And a different agent reviews\nevery change before it lands."),
    ("v10", 2, "Changes requested?"),
    ("v10", 5, "It repairs, and tries again."),
    ("v10", 3, "But never forever."),
    ("v11", 5, "Your branches are never touched."),
    ("v12", 2, "557 tests."),
    ("v12", 3, "Crash-safe resume."),
    ("v12", 2, "Secrets redacted."),
    ("v13", 6, "Open source, on GitHub and PyPI."),
    ("v14", 7, "See it in 60 seconds, for free."),
    ("v15", 1, "Orkestra."),
]
LEAD, TAIL, GAP = 0.08, 0.30, 0.04


def ts(x):
    ms = int(round(max(0.0, x) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def cues():
    pos, out = {}, []
    for k, n, text in CUES:
        for line in text.split("\n"):
            assert len(line) <= 42, f"{k}: caption line over 42 characters: {line!r}"
        words = VO[k]["words"][pos.get(k, 0): pos.get(k, 0) + n]
        assert len(words) == n, f"{k}: the voiced take has fewer words than the captions use"
        pos[k] = pos.get(k, 0) + n
        out.append([words[0]["t0"] - LEAD, words[-1]["t1"] + TAIL, text])
    for k, line in VO.items():
        assert pos.get(k, 0) == len(line["words"]), f"{k}: {len(line['words']) - pos.get(k, 0)} voiced words not captioned"
    for a, b in zip(out, out[1:]):
        a[1] = min(a[1], b[0] - GAP)
    return out


C = cues()
(ROOT / "renders").mkdir(exist_ok=True)
(ROOT / "renders/orkestra-v2-calm.en.vtt").write_text("WEBVTT\n\n" + "".join(
    f"{i}\n{ts(a)} --> {ts(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(C, 1)))
print(f"renders/orkestra-v2-calm.en.vtt: {len(C)} cues")
