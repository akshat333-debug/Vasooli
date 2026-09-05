# Demo runbook

Everything to do by hand, in order, to record the five-minute video.

The voiceover is generated separately from [`VOICEOVER.txt`](VOICEOVER.txt) and
laid over the screen recording afterwards.

---

## 0. Do this first — generate the audio before you record

Counter-intuitive but much easier: **make the voice track first, then record the
screen to fit it.** Matching video to a fixed audio length is simple; matching
audio to a fixed video length means re-generating and re-timing repeatedly.

1. Open `docs/VOICEOVER.txt`.
2. Generate **four separate audio files**, one per segment — not one long file.
   Separate files let you nudge each segment independently when a command takes
   longer than expected. Name them `seg1.mp3` … `seg4.mp3`.
3. Note each file's duration. At 155 words per minute the script measures:
   segment one **2:45**, segment two **0:56**, segment three **0:19**, segment
   four **0:50** — **4:50 total**, which fits under the five-minute limit with
   about ten seconds of headroom.
4. If your voice reads slower and the total exceeds 5:00, cut in this order:
   the ablation paragraph in segment one ("Then I tried to break my own
   thesis…", 30 words), then the Rulebook paragraph in segment two. Both are
   legible on screen without narration. Do **not** cut the calibration
   paragraph or the total-rupees line — those are the honesty beats, and they
   are the reason the pitch works.

**Voice settings:** pick a measured, even-paced voice. Avoid anything
enthusiastic — the script's persuasion comes from the numbers being unflattering,
and an excited read fights it. Speed 0.95–1.0. If your generator supports it,
add a short pause between paragraphs; the script is written in paragraph blocks
that correspond to what is on screen.

---

## 1. Environment prep (before recording, not on camera)

```bash
cd /Users/agraw/Desktop/personal/projects/Hackathons/Razorpay/vasooli
uv sync
uv run pytest -q          # expect: 229 passed
```

Confirm `.env` exists and holds a **test-mode** Razorpay key. `vasooli live`
makes real API calls to the test account. It is gitignored; check it is still
untracked with `git status`.

**Terminal appearance.** This is on camera for two of five minutes:

- Font size up to at least 16pt. Judges may watch on a laptop.
- Window wide enough for 80 columns without wrapping — the report tables are
  aligned to 78 characters and wrapping destroys them.
- Light-on-dark or dark-on-light both fine; high contrast matters more.
- Clear the scrollback (`cmd-K`) before each command so each one starts clean.
- Turn off any shell prompt that prints git status, timing, or a full path — it
  is noise between commands.

**Pre-stage the ledger tamper demo.** Do not type SQL live. Have the Ledger page
open with the tamper control visible; it is a button on the page.

**Do one full dry run** end to end with the audio playing. Note where you fall
behind. Nothing in the script depends on a command finishing at an exact moment,
but you want to know which ones are slow before you are recording.

---

## 2. Reset to a clean state

Immediately before the take:

```bash
rm -f vasooli.db worklist.csv && clear
```

This matters. A leftover `vasooli.db` makes `explain` print "6 older rows from
earlier runs not shown", which invites a question you do not want to spend time
on.

---

## 3. Segment 1 — Terminal (~2:45)

Run these **live, in this order**. Do not paste pre-captured output; the point
is that it is running.

```bash
uv run vasooli seed
```
```bash
uv run vasooli run
```
```bash
uv run vasooli explain sub_SYN0056
```
```bash
uv run vasooli experiments --seeds 40
```
```bash
uv run vasooli demo-trip
```
```bash
uv run vasooli live
```

Notes on each:

| Command | Watch for | Runtime |
|---|---|---|
| `seed` | The hazard counts at the bottom | instant |
| `run` | Scroll to the HEADLINE block and hold there while segment one's money paragraph plays | ~10s with LLM |
| `explain` | Scroll so all 7 rules and the FIRED line are visible | instant |
| `experiments` | Scroll to section **1c** (total rupees) and to the calibration warning — both are the honesty beats | ~40s |
| `demo-trip` | The trip line | instant |
| `live` | The subscription ID and the "activation requires customer mandate authentication" line | ~3s, needs network |

`run` prints one harmless first line: `no pricing for model 'claude-haiku-4.5';
counting cost as $0`. That is RunFuse saying it cannot price the model, so the
cost ceiling never trips. It is explained in `diagnose.py`. Ignore it; if asked,
that is the answer.

**If `live` fails** (no network, rate limit): do not stop the recording. It is
the last command in the segment. Let it fail on camera and keep going — the
script's line about it stopping short of activation still lands, and a system
failing honestly on camera is not the disaster it feels like. You can also cut
that beat in editing.

---

## 4. Segment 2 — Browser (~1:30)

Open <https://akshat333-debug.github.io/Vasooli/> — the deployed site, not
localhost. It proves the thing is actually shipped.

In order:

1. **Home.** Start at the top so the headline is visible. Scroll slowly to the
   attempt grid and let it sit.
2. **Home, escalation queue.** Scroll further. Point at the ₹73,000 AFA row.
3. **Rulebook.** Click through. Scroll so several of the 7 rules are visible
   with their legal basis column.
4. **Ledger.** Scroll to the tamper control. Click it. Let the chain break
   render — the verifier names the row. Then restore it.
5. **Records.** Click one row to expand. Any row; a refused one is better.

Move deliberately. Fast scrolling reads as nervous and the text becomes
unreadable in compressed video.

---

## 5. Segment 3 — Code (~0:25)

Open `vasooli/decide.py` in the editor, scrolled to the top so the module
docstring and the first rules are on screen. Do not scroll during this segment —
the narration is about what the file *is*, not a code tour.

---

## 6. Segment 4 — Close (~0:45)

Back in the terminal:

```bash
uv run pytest -q
```

Let it print `229 passed`. Stop recording once that line is on screen and the
last sentence of narration has finished.

---

## 7. Assembly

1. Import the screen recording.
2. Drop `seg1.mp3` at 0:00, then place each subsequent segment at the moment the
   corresponding visual starts. Do not try to lip-sync to individual commands —
   align each segment's start and let the middle drift.
3. If a segment's audio runs past its visuals, **hold the last frame** rather
   than rushing the next section.
4. Mute the original screen-recording audio entirely.
5. Export 1080p. Check the terminal text is legible after compression — if not,
   re-record with a larger font. This is the most common way a good demo
   becomes unwatchable.
6. Upload to YouTube as **unlisted**. Confirm the link opens in a private window
   before submitting it.

---

## 8. Final pre-submit checks

```bash
uv run pytest -q                 # 229 passed
uv run ruff check vasooli tests  # All checks passed
git status                       # clean, and .env still untracked
```

- The live site loads: <https://akshat333-debug.github.io/Vasooli/>
- The repo is public: <https://github.com/akshat333-debug/Vasooli>
- The video link opens in a private window.
- README §1 and the video agree on what `halted` means. This was wrong until
  5 Sep 2026 and is the single claim most likely to be challenged.

---

## 9. If you are asked a question on the day

Prepared answers live in [`APPLICATION_NOTES.md`](APPLICATION_NOTES.md) — scaling,
LLM unavailability, "show me a failure", the 2.3% objection, `halted`
reversibility, and the T+1/T+3/T+5 attribution. Read them once the morning of.

Two things worth having on the tip of your tongue, because they are the
project's weakest points and pretending otherwise is worse than owning them:

- **The scheduler is over-confident by 0.14 in its top probability bucket.** It
  is most wrong exactly where it is most sure. `vasooli experiments` prints this
  itself.
- **On raw rupees collected, the sequencer wins 25 of 40 seeds, not 40.** The
  40 of 40 figure is rupees per attempt. Section 1c prints both.
