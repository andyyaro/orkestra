# Orkestra launch film: storyboard and build

62.5 s, 1920 × 1080, 30 fps. H.264 (High, BT.709) with AAC at about 200 kb/s; measured on the MP4:
-16.0 LUFS integrated, true peak -1.3 dBTP, loudness range 5.5 LU. This is v2, the calm cut. Every
claim in it and its source is in [FACTS.md](FACTS.md); the brief it was made from is
[SPEC.md](SPEC.md).

SPEC.md was written for the v2 draft: its TIME line (63.3 s, "Trap" by Arulo at 152 BPM) and its
shot times are the draft's. The calm cut keeps the draft's scenes and look, and moves them onto
"Peace" at 120 BPM; the times below are the calm cut's.

## What is real and what is rebuilt

- **Real:** the text in every window. It comes from one run of `orkestra demo` on Orkestra 0.5.5
  (run `run_522f70d8`): the plan, the worktree branches, the gate passing, the reviewer's verdict,
  the repair log, the commit each task landed as, and the terminal output in the "try it" scene.
  The numbers and defaults on screen (557 tests, `max_review_cycles = 2`, `[REDACTED]`) are the
  project's own.
- **Rebuilt:** the windows themselves. None is a screen recording: `orkestra watch`, the demo's
  output, the diff, the review and the logs are redrawn in HTML in the film's colours, some long
  lines trimmed, so each line can arrive on the word that names it.
- **Made up:** the GitHub token in the "secrets redacted" beat. It is fake, and the film keeps
  `GITHUB_TOKEN=` in front of the marker where the real redactor replaces the whole assignment.

## The film

| Time (s) | Scene | Narration | What you see |
|---|---|---|---|
| 0–11.4 | The problem | "You already use coding agents. Claude Code. Codex. Antigravity. One at a time is slow. All at once is chaos." | Kicker "00 / the problem". Big lowercase headlines on one stage, swapped with a blur: "you already use coding agents.", where "agents." rolls through "claude code.", "codex." and "antigravity." like a slot machine; "one at a time is slow."; "all at once is chaos." with "chaos." in red |
| 11.4–20.0 | Meet Orkestra | "Meet Orkestra. Many coding agents. One repo. Nothing lands unreviewed." | The `orkestra watch` window slides in on the build and lands on the music's drop (12.0 s); its rows run from pending through running, verifying and reviewing to done. "meet orkestra." and the list "many coding agents / one repo / nothing lands unreviewed", each on its word |
| 20.0–31.75 | How it works | "A director plans the work, and every task runs in its own Git worktree. Your tests are the referee. And a different agent reviews every change before it lands." | One big window. "01 / plan": the plan, and each task with its worktree branch. "02 / verify": `python check_demo.py`, "your gate, run by Orkestra", PASS on both tasks. "03 / review": the window splits in two, ada's diff of `feature_a.py` and grace's verdict, "demo reviewer wants a docstring". One grey caption under each beat |
| 31.75–40.0 | Repair and safety | "Changes requested? It repairs, and tries again. But never forever. Your branches are never touched." | "04 / repair" (bounded, never forever): "changes requested?" in red beside the log of the repair, line by line, to "task feature-a done, landed as 2d63c4c"; the chip "bounded · max_review_cycles = 2". Then "05 / safe" (your repo, untouched): "your branches are never touched.", with the line from `orkestra review` under it |
| 40.0–50.0 | Proof and open source | "Five hundred and fifty-seven tests. Crash-safe resume. Secrets redacted. Open source, on GitHub and PyPI." | "06 / proof": 557 counts up along a thin track, "tests, all passing.", "pytest, Orkestra v0.5.5"; `orkestra resume`; a token turns into `[REDACTED]`. "07 / open source": "open source." with github.com/andyyaro/orkestra, `pypi: orkestra-runtime`, `apache-2.0 · v0.5.5` |
| 50.0–56.0 | Try it | "See it in sixty seconds, for free." | "08 / try it": "see it in 60 seconds. free."; a terminal types `orkestra demo` and prints five of its real lines; "No agent CLIs. No logins. No tokens spent." |
| 56.0–62.5 | End card | "Orkestra." | The mark draws (node, branches, the red gate, the result) and the wordmark resolves on the voice; the install command `uv tool install 'orkestra-runtime[tui]'` as the one red button; github.com/andyyaro/orkestra |

## Look

- **Style:** the grammar of HyperFrames' own Linear launch showcase, in Orkestra's colours: a
  near-black ground with an 80 px hairline grid, grain and two soft lights; huge lowercase
  headlines set left and tightly tracked; real product windows set dim; one grey caption under a
  window; one red word per headline; swaps are blurs on one stage, with no hard cuts.
- **Brand:** Orkestra's own (`docs/assets/brand/`): ink #161412 as the ground, cream #F2EEE6 for
  text, signal red #E8391F for the kicker, one word per headline, the chips and the end button.
  Grey #9A948A for captions. Terminal PASS and ok use #8FBF8A, the product's own green.
- **Type:** Geist SemiBold for headlines (-0.055em), Geist Medium for lists, Geist for captions,
  Montserrat SemiBold capitals for kickers and chips, Geist Mono inside the windows. No em dashes on
  screen.
- **Motion:** arrivals ease out, camera and window moves take 0.5–0.6 s with an 8–12 px blur,
  exits take about half the time of the entrance. Headline words blur in on the voice's own word
  times (`window.VO`); landed titles hold still.

## Sound

- **Voice:** Kokoro-82M, voice af_heart, 15 lines, voiced at speeds 1.0 and 1.08. `pick.py`
  transcribes each take with mlx-whisper (large-v3-turbo), keeps the one that matches the script
  best and times its words. The spellings for the ear are in `narration/lines-tts.json`:
  "Orchestra", "Pie Pee Eye", and "Changes, requested?" (without the comma, "Changes requested" is
  heard as "Change is requested").
- **Music:** "Peace" by Diego Nava (Mixkit 487), 120 BPM, cut on its bar lines by `sound/music.py`.
  The film's bars 0–27 are the track's bars 10–37: its keys alone under the problem, its one-bar
  build at 10.0 s, and its drums and bass dropping on "Meet Orkestra" at 12.0 s. At the end card
  (56.0 s) it skips to the track's bar 46, the same point in the same two-bar groove, and the
  track's own ending plays out from 58.0 s. Each join has a 12 ms crossfade.
- **Effects:** 34 soft Mixkit effects, each on something that happens on screen (`sfx_events` in
  `sound/mix.py`): ticks on the rolling agent names, the plan rows, the log lines and the terminal
  output; pops on the gates passing, the chips, 557 and the install button; whooshes on windows
  arriving; sweeps on "chaos." and the big swaps; a harder pop on `[REDACTED]`; a short burst of
  typing; one riser into the end card. Each peak lands one frame after its picture. The list is
  in [assets/audio/SOURCE.md](assets/audio/SOURCE.md).
- **Levels:** the voice is clear on top at -16 LUFS. The music sits about 13.5 dB under it while
  it speaks and 9 dB under between lines. The mix is -16 LUFS with true peak under -1 dBTP.

## Build

Get the inputs first: `tools/fetch_vendor.sh` for GSAP, then the fonts, music and effects listed
in [assets/audio/SOURCE.md](assets/audio/SOURCE.md). The Python steps need numpy, soundfile,
librosa and mlx-whisper; voicing needs Kokoro-82M through mlx-audio.

```sh
tools/fetch_vendor.sh
# Voice each line of narration/lines-tts.json with Kokoro-82M (af_heart) at speeds 1.0 and 1.08,
# as narration/takes-kokoro/<id>.<k>.wav
python3 narration/pick.py takes-kokoro       # best take per line, narration/chosen/, words.json
python3 -I sound/music.py                    # assets/audio/music.wav, sound/grid.json
python3 -I sound/mix.py                      # mix.wav, vo.wav, assets/vo.js, assets/timing.js
python3 -I build.py                          # scene windows into index.html
python3 -I captions.py                       # renders/orkestra-v2-calm.en.vtt
npx --yes hyperframes@0.8.173 check
npx --yes hyperframes@0.8.173 render -o renders/orkestra-v2-calm.mp4 --fps 30
```

The render takes its sound from the `<audio>` element in `index.html` (`assets/audio/mix.wav`).
The scenes read their timing from `window.TM` (`assets/timing.js`) and find their cue words by
text in `window.VO`, so a new voice or new line slots (`SLOTS` and `SCENES` in `sound/mix.py`)
re-time the film by themselves.

## The README preview

`docs/assets/readme/orkestra-in-action.webp` is the "how it works" and repair scenes, 20.0–36.0 s
of the film: the plan with its worktree branches, the gate passing, the two windows of the review,
and the log of the repair, at 1200 × 676 and 15 fps, 3.9 MB. Every frame is a keyframe
(`-kmax 1`). With partial frames, lossy WebP kept 8 × 8 blocks of the previous frame wherever the
picture changed by only a few levels, and the dark windows fading in over the dark ground left
squares of the old grid inside them until the next keyframe.

```sh
mkdir -p preview
ffmpeg -ss 20.0 -t 16 -i renders/orkestra-v2-calm.mp4 \
  -vf "fps=15,scale=1200:676:flags=lanczos" preview/f%03d.png
img2webp -loop 0 -kmax 1 -lossy -q 90 -m 6 -d 67 preview/f*.png \
  -o ../../docs/assets/readme/orkestra-in-action.webp
```
