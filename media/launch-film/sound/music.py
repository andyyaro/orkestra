"""Cut "Peace" (Diego Nava, Mixkit 487, free licence: assets/audio/SOURCE.md) to the film.

    python3 -I sound/music.py        # -> assets/audio/music.wav (48 kHz stereo), sound/grid.json

The track is 120 BPM: track bar n starts at 0.4 + 2n s. Bars 0-14 are keys alone, bar 15 (30.4 s) is a one-bar build,
the drums and bass drop on bar 16 (32.4 s); one steady groove (a two-bar cycle) runs to bar 46, bar 47 is its ending
and bar 48 its decay.

The film's bar grid starts at 0: film bar b starts at 2b s.
- Film bars 0-27 are track bars 10-37: six bars of keys, the build on film bar 5, the drop on film bar 6 (12.0 s).
- At film bar 28 (56.0 s, the end card) it skips to track bar 46. Both are even bars of the same two-bar groove, so
  the join is seamless. The track's own ending then plays from film bar 29 (58.0 s) and decays to the end.
Each join has a 12 ms crossfade. The music fades in over 0.4 s.
"""
import json, subprocess
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TRACK = ROOT / "sound/track.mp3"
SR, BAR, OFF = 48000, 2.0, 0.4
CUTS = [(0, 10), (28, 46)]          # (film bar, track bar) where each piece starts
FILM_END = 62.5                     # seconds
XF = 0.012


def main():
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(TRACK), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    track = np.frombuffer(raw, np.float32).reshape(-1, 2).T.astype(np.float64)
    n = int(FILM_END * SR)
    out = np.zeros((2, n))
    x = int(XF * SR); ramp = np.linspace(0, 1, x)
    for k, (fb, tb) in enumerate(CUTS):
        f0 = int(fb * BAR * SR)
        f1 = int(CUTS[k + 1][0] * BAR * SR) if k + 1 < len(CUTS) else n
        t0 = int((OFF + tb * BAR) * SR)
        seg = track[:, t0: t0 + (f1 - f0) + x]
        seg = np.pad(seg, ((0, 0), (0, max(0, (f1 - f0) + x - seg.shape[1]))))
        if k == 0:
            out[:, f0:f1] = seg[:, : f1 - f0]
        else:   # crossfade into the new piece across the join
            out[:, f0 - x: f0] = out[:, f0 - x: f0] * (1 - ramp) + track[:, t0 - x: t0] * ramp
            out[:, f0:f1] = seg[:, : f1 - f0]
    fi = int(0.4 * SR); out[:, :fi] *= np.linspace(0, 1, fi)
    fo = int(0.6 * SR); out[:, -fo:] *= np.linspace(1, 0, fo)
    import soundfile as sf
    (ROOT / "assets/audio").mkdir(parents=True, exist_ok=True)
    sf.write(ROOT / "assets/audio/music.wav", out.T.astype(np.float32), SR)
    grid = {"bpm": 120, "beat": 0.5, "bar": BAR, "offset": 0.0, "drop": 6 * BAR, "end_card": 28 * BAR,
            "track_ending": 29 * BAR, "duration": FILM_END, "cuts": CUTS}
    (ROOT / "sound/grid.json").write_text(json.dumps(grid, indent=1))
    print(f"music.wav {FILM_END} s; drop at {6 * BAR} s, end card {28 * BAR} s, track ending {29 * BAR} s")


if __name__ == "__main__":
    main()
