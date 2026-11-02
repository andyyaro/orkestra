# Orkestra launch film

The 63-second film at the top of the [repository README](../../README.md), published at
https://andyyaro.github.io/orkestra/film.html. It says what Orkestra does for someone who has never
heard of it: many coding agents on one repository, every task in its own Git worktree, your tests
as the referee, a different agent reviewing every change, and a bounded repair loop when a review
says no. It ends on the command to try it. Every window in it is drawn in HTML with the text of a
real `orkestra demo` run; the headlines carry the story with the sound off.

This is the second version, the calm cut. [STORYBOARD.md](STORYBOARD.md) has the scenes, the look,
the sound and every build step. [FACTS.md](FACTS.md) has every claim in the film and where it comes
from. [SPEC.md](SPEC.md) is the brief the film was made from.

## What is here

| Path | What it is |
|---|---|
| `index.html`, `compositions/` | The composition (HyperFrames 0.8.173, GSAP): one file per scene, plus `code-terminal-run.html`, the HyperFrames registry's terminal, filled with real `orkestra demo` output |
| `build.py` | Writes the scene windows from `sound/timing.json` into `index.html` |
| `captions.py` | Writes the narration as a captions file (WebVTT) from its word times; added with this folder, after the render |
| `narration/` | The script (`lines.json`), the script as voiced (`lines-tts.json`), `pick.py`, which chooses the best take of each line and times its words, and those word times (`words.json`) |
| `sound/` | The music edit (`music.py`) and the mix (`mix.py`): narration, music and effects, each effect on something that happens on screen |
| `assets/vo.js`, `assets/timing.js`, `sound/grid.json`, `sound/timing.json` | The narration's word times and the scene windows the scenes read, as the film was rendered. The steps make them again; they are kept so the composition opens without re-voicing it |
| `assets/wordmark-cream.svg` | The Orkestra wordmark the end card uses |
| `tools/fetch_vendor.sh` | Fetches GSAP at the pinned version and checks the file's SHA-256 |
| `deploy/film.html`, `deploy/index.html` | The watch page, and a redirect to it from the site's root |
| `assets/audio/SOURCE.md` | Every third-party sound, font and piece of code in the film, with its licence and where it goes |
| `FACTS.md` | Every line of narration and every on-screen claim, with its source |
| `SPEC.md` | The film's brief: goal, look, motion, shots and what is banned |

## What is not here, and why

The working folder for this cut is about 75 MB (127 MB with v1). This folder keeps the source
and leaves out everything that is generated or that its licence does not let us hand on by itself:

- **Generated:** the narration takes and the chosen take of each line, the music edit, the mix,
  the voice stem, the renders and the review snapshots. The build steps make them again.
- **Screen recordings:** there are none. The windows are drawn from the text of a real run.
- **Third-party media:** the music ("Peace" by Diego Nava, Mixkit) and eight Mixkit sound effects.
  [assets/audio/SOURCE.md](assets/audio/SOURCE.md) lists each one with its licence and the path it
  goes to.
- **Libraries and fonts:** GSAP 3.14.2 is fetched by `tools/fetch_vendor.sh`. The Geist, Geist Mono
  and Montserrat fonts (SIL OFL 1.1) go in `assets/fonts/`.
- **Earlier versions:** v1 (Andy's cloned voice, "Trap" by Arulo, a cream look with the mark as the
  diagram) and the v2 draft came before this cut. v1's source stays in the film's working folder.

## Publishing

The MP4, its captions and its poster are assets of the
[`film-v1` release](https://github.com/andyyaro/orkestra/releases/tag/film-v1), so the 7.9 MB
film is not in the repository's history. The
[film page workflow](../../.github/workflows/film.yml) puts them on GitHub Pages with
`deploy/film.html`, `deploy/index.html`, the logo and the icon. It runs when anything in
`deploy/` changes on `main`. After replacing a release asset, run it by hand:

```sh
gh release upload film-v1 orkestra-launch.mp4 --clobber
gh workflow run film.yml
```

## Credits

Narration: Kokoro-82M (Apache-2.0), voice af_heart. Music: "Peace" by Diego Nava (Mixkit). Sound
effects: Mixkit. The terminal in the "try it" scene is HyperFrames' `code-terminal-run` (Apache-2.0).
Type: Geist, Geist Mono and Montserrat (SIL OFL 1.1).
