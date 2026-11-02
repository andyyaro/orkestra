# Third-party sounds and type in the film

These are in the film but not in this repository. Their licences cover using them inside a film,
not handing the files on by themselves, so they are listed here instead. Download each one again
to the path shown to rebuild.

## Music

| Used as | Track | Licence | Put it at |
|---|---|---|---|
| The bed under the whole film, cut on its bar lines by `sound/music.py` | "Peace" by Diego Nava, Mixkit 487 (https://assets.mixkit.co/music/487/487.mp3) | [Mixkit Stock Music Free License](https://mixkit.co/license/#musicFree): free in any project, no credit required, not for use in a music-only track or for registering with a rights-management (Content ID) service | `sound/track.mp3` |

## Sound effects

All from Mixkit, under the [Mixkit Sound Effects Free License](https://mixkit.co/license/).
The names are the ones `sound/mix.py` uses (`SFX`); each file goes in `sound/sfx-src/` as
`mixkit-<id>.mp3`.

| Name in `mix.py` | Mixkit id | What it marks |
|---|---|---|
| `tick` | 1120 | The agent names rolling in, the plan rows, the repair log's lines, the terminal's output lines |
| `pop` | 2357 | The gates passing, the review chips, the bound chip, 557 landing, the install button |
| `pop_hard` | 3005 | The token turning into `[REDACTED]` |
| `whoosh_wind` | 1465 | The watch window landing on the drop; the log window sliding in |
| `whoosh_air` | 1492 | The second window of the review sliding in |
| `sweep` | 3115 | "chaos." whipping in; the window growing into the next scene; the swap to "your branches" |
| `typing` | 2538 | The terminal typing `orkestra demo` (0.75 s from the middle of the take) |
| `riser` | 2408 | The swell into the end card |

## Voice

Kokoro-82M ([Apache-2.0](https://huggingface.co/hexgrad/Kokoro-82M)), voice af_heart, run
locally through mlx-audio. The lines are `narration/lines-tts.json`; the audio is generated, so it
is not kept.

## Type

Geist (Regular, Medium, SemiBold, Bold), Geist Mono (Regular, Medium, SemiBold) and Montserrat
SemiBold, all under the [SIL Open Font License 1.1](https://openfontlicense.org/), as `.woff2`
files in `assets/fonts/` with the names the composition loads (`Geist-Regular.woff2`, …,
`GeistMono-Regular.woff2`, …, `Montserrat-SemiBold.woff2`).

## Code

The terminal in the "try it" scene, `compositions/code-terminal-run.html`, is the `code-terminal-run`
component from the [HyperFrames](https://github.com/heygen-com/hyperframes) registry (Apache-2.0),
with its content replaced by real `orkestra demo` output. Its header comment is kept as it came.
GSAP 3.14.2 is fetched by `tools/fetch_vendor.sh` and is under GreenSock's
[standard licence](https://gsap.com/standard-license).
