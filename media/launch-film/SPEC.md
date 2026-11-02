# Orkestra launch film, v2: SPEC

```text
GOAL:    a developer who has never heard of Orkestra knows what it does, why to trust it, and types
         `uv tool install 'orkestra-runtime[tui]'` to try it.
OUTPUT:  HyperFrames 0.8.173, 1920 x 1080, 30 fps.
TIME:    63.305 s x 30 = 1899 frames. Music "Trap" (Arulo) cut to 152 BPM: 11.84 frames a beat,
         bar b starts at 0.419 + 1.5790 b s. The drop is bar 8 (13.051 s), the final hit bar 36 (57.262 s).
LOOK:    The reference is HyperFrames' own launch showcase for Linear
         (docs/guides/product-launch-video.mdx, "example-product-launch-v2.mp4"). Its grammar, measured:
         a near-black ground with an 80 px hairline grid (24 columns at 1920), grain, one soft radial light;
         huge lowercase headlines, set left and tightly tracked; a mono caps kicker in the accent
         ("00 / THE PROBLEM"); real product windows set dim, with grey traffic-light dots; one grey caption
         line under a window; one accent word per headline; the logo centred on a soft glow, and one button.
         Swaps are blurs on one stage; the ground never cuts. There are no hard cuts in the reference.
         Here the brand replaces the reference's indigo:
           ground  #161412 (Orkestra ink) + grid rgba(242,238,230,.05) 1 px every 80 px + grain 7% overlay
                   + radial light: cream 7% upper left, red #E8391F 16% lower right; vignette 30%
           ink     #F2EEE6 (cream); secondary #9A948A; dim #57514A
           accent  #E8391F: the kicker, one word or underline per headline, the chips, the end button.
                   Terminal "PASS/ok" uses #8FBF8A (the product's own colour), nothing else does.
           type    display Geist SemiBold 600, -0.055em, line-height .96, lowercase:
                   200 px for the problem and "open source." headlines, 112-120 px beside a window;
                   kickers and chips Montserrat SemiBold 600 24 px, +0.12em, caps ("00 / THE PROBLEM": label red,
                   description grey; Andy rejected the mono-caps kicker); lists Geist Medium 38 px;
                   captions Geist 400 34 px #9A948A; terminal Geist Mono 400 22-26 px.
           windows #1D1A17, 1 px rgba(242,238,230,.09) border, radius 14, title bar 44 px with three
                   #3A3530 dots; shadow 0 40px 90px rgba(0,0,0,.5).
         Key text sits inside the 80% title-safe box (x 192-1728, y 108-972).
OBJECTS: the real product only: `orkestra watch` (Textual TUI, v0.5.5), the real `orkestra demo` output,
         the real review verdict (grace -> "demo reviewer wants a docstring"), real branch names
         (ork/run_522f70d8/task_…), real `orkestra review` summary, the real default max_review_cycles = 2,
         557 tests (pytest on v0.5.5), the real [REDACTED] marker; the brand mark and wordmark.
MOTION:  arrive expo.out / power4.out; camera and window moves power2.inOut 0.5-0.6 s with blur 8-12 px;
         exits power3.in, 40-50% of the entrance. Headline words: blur 8px -> 0 and opacity 0 -> 1 in
         0.16 s, timed to the voice's own word times (window.VO). Kickers: per-letter type-on.
         Landed titles hold dead still. Slot roll for the agent names: 0.12 s a roll.
SHOTS:   s1 problem   0-11.80    four headlines on one stage, blur swaps; "agents." rolls through
                                  claude code / codex / antigravity; "chaos." in red.
         s2 meet      11.80-20.95 the watch window slides in on the build and lands on the drop; "meet orkestra."
                                  + three list lines on the voice; the TUI rows run to done.
         s3 how       20.95-32.00 one big window: plan -> gates PASS -> it splits into two windows
                                  (ada wrote / grace reviews). Kicker + caption swap per beat.
         s4 repair    32.00-38.31 "changes requested?" + the real log of the repair; the bound chip;
                                  then "your branches are never touched." + the real review summary.
         s5 proof     38.31-50.95 557 counts up on a track (mk-progress-stat grammar); crash-safe resume;
                                  a token turns to [REDACTED]; then "open source." + where to get it.
         s6 try       50.95-57.26 "see it in 60 seconds. free." + the registry's code-terminal-run
                                  running `orkestra demo` with its real output.
         s7 end       57.26-63.31 the mark draws, the wordmark resolves on the final hit; the install command
                                  as the one button; github.com/andyyaro/orkestra.
BANNED:  em dashes anywhere on screen (Andy's rule); mono-caps kickers; v1's look: Syne display headlines, agent cards in a row, conflict-message floods, frame shake,
         invented diagrams, the logo docked in a corner, three feature cards, a title over a dimmed screenshot,
         floating or breathing loops, everything centred, everything fading and sliding up, glows anywhere
         but behind the final mark.
QA:      2.6 (first headline), 5.6 (antigravity rolled in), 10.3 (chaos), 13.2 (window landed on the drop),
         19.3 (meet + full list), 24.6 (plan rows), 27.0 (PASS), 30.4 (two windows), 35.9 (bound chip),
         37.8 (never touched), 40.2 (557), 42.8 (REDACTED), 48.0 (open source), 54.6 (terminal), 60.5 (end).
```

Registry items used: `code-terminal-run` (component, mounted as a scene), `mk-progress-stat` (its stat
grammar: numeral, label, thin track), the `transitions` "blur swap on one stage" from the skill.
