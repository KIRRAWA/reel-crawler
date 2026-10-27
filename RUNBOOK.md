# Runbook — Reels collector (review-toolchain branch)

All commands run from the `reel-crawler/` directory. No `env -u ...` prefix is
needed: dead proxy environment variables are stripped in-process at startup.

## 0. One-time setup

```bash
source .venv/bin/activate        # activate the project virtualenv if not already active
ollama ps                        # confirm Ollama is running
ollama pull qwen2.5vl:3b         # pull the vision model once
```

## 1. Pre-flight (before any browser-using command)

```bash
pgrep -fl instagram-session      # must print nothing; pkill -f instagram-session otherwise
python feed_collector.py --check # dependencies + local vision model check
```

Run only one browser-using task at a time: Edge hands a second launch with the
same profile to the existing instance and the new run fails silently.

## 2. Reset data / switch account

```bash
rm -rf feed_candidates_mine review_frames review_videos instagram-session
# keep the old dataset instead: mv feed_candidates_mine feed_candidates_old_account
```

## 3. Log in (persists the session to instagram-session/cookies.txt)

```bash
python feed_collector.py --login
```

Sign in manually in the browser, return to the terminal, press Enter.
Cold-account discipline: no manual likes/follows/taps while logged in.

## 4. Collect (scroll-only, fixed 5s dwell per Reel, never screens)

```bash
python feed_collector.py --target 50 --output feed_candidates_mine
# faster scroll (do not go below 3):  --delay 3
# feed did not load a video:          --manual-start  (open a playing Reel, then Enter)
```

Collection never screens in this branch: inline screening was removed so the
account's engagement signal stays uniform. Ctrl+C saves progress; re-running
continues (duplicates are skipped).

## 5. Screen offline (no browser, resumable, parallel)

```bash
python feed_collector.py --rescreen --target 100 --output feed_candidates_mine \
  --frame-interval 5 --vision-batch 0 --speech-model base --workers 3
# more GPU parallelism: prefix with OLLAMA_NUM_PARALLEL=2
```

Rescreen only retries items whose last attempt produced no result
(`not_screened` / `screening_failed:*`), so an interrupted run resumes safely.

Human-only screening is the default (`--llm off`): the vision model is never
called and every item lands in the review queue. Add `--llm on` to let the
model pre-screen, with humans reviewing only what the model flags.

## 6. Human review (optional, recommended)

```bash
# capture frame evidence first (zero model calls): 10 frames per video,
# spread evenly across its duration (change with --n)
python review_capture.py --store feed_candidates_mine --frames review_frames
# only some items: --only CODE1 --only CODE2 ; re-capture: --force
# one reel by link:  python review_capture.py --url https://www.instagram.com/reel/AbCd1234/
# every team-pool video without frames:  python review_capture.py --pool

# keyboard review queue at http://127.0.0.1:8765
python review_gui.py --store feed_candidates_mine --frames review_frames
# keys: g approve · w reject · r choose category (1-12) · u undo · arrows focus frames
# items with fewer than 10 frames show a "Capture 10 frames from link" button
```

## 6b. Multi-reviewer team sync (every member reviews every video)

A private GitHub repo is the hub: only opinions + public metadata travel (no
videos, frames, or transcripts — IRB rule). The videos stay local and are
re-downloaded from their URLs when a reviewer needs to watch one.

### The easy way — the team hub GUI (covers everything below)

Full step-by-step walkthrough: **TEAM-TUTORIAL.md**.

```bash
python team_gui.py        # or: python review_team.py gui  ->  http://127.0.0.1:8766
```

One page for setup + accounts + login + sync + progress + disputes:

1. **Shared repo** — paste the GitHub repo URL once. A single lab GitHub
   account is enough for the whole team: paste its token, and every member
   pushes with that same credential — no need to add members as GitHub
   collaborators. People are told apart by their own account + password
   (step 2); every git commit is authored with that account name. Leave the
   token empty to use each machine's own GitHub access (e.g. SSH) instead.
   The token lives only in this machine's local `.git/config` — it never
   enters the shared repo.
2. **Member accounts** — create one username + password per person (only
   salted PBKDF2 hashes are stored and synced).
3. **Log in** — each member logs in with their own password; the page pulls
   the latest team state and can open the review queue for you.
4. **Sync** — pull before reviewing / push after (the review queue also
   auto-pushes after every decision).
5. **Disputes** — the videos reviewers disagree on, in one table.
6. **Add videos to the pool** — paste reel links, one per line, and every
   member's review queue picks them up after their next pull. For videos
   the team got outside the collector (e.g. downloaded locally); only
   public metadata (URL, @author, likes, caption) is shared.

### The command-line way (same functions)

One-time setup, first machine (private repo, e.g. under KIRRAWA):

```bash
python review_team.py init git@github.com:KIRRAWA/<private-repo>.git
python review_team.py account add david      # prompts for a password
python review_team.py login david
```

Every other machine:

```bash
git clone git@github.com:KIRRAWA/<private-repo>.git sync_repo
python review_team.py account add <member>   # add that machine's member
python review_team.py login <member>
```

Every reviewer's daily loop:

```bash
python review_team.py sync pull              # fetch everyone's new videos + opinions
python review_team.py pool add <reel-url> ...   # hand-add videos for everyone to review
python feed_collector.py --rescreen --target 100 --output feed_candidates_mine
python review_gui.py --store feed_candidates_mine --frames review_frames
#   -> team mode: the queue is the whole pool minus YOUR opinions;
#      every g/w/r/u decision is pushed to GitHub immediately
python review_team.py status                 # everyone's progress
python review_team.py disputes               # table of videos reviewers disagree on
```

Notes:
- `feed_collector.py` auto-pushes new items after every run (skipped silently
  on failure, so offline collection still works).
- `review_gui.py` auto-pulls at startup and pushes after every decision.
- Undo rewrites the opinion file; historical opinion lines are kept.
- Disputes = a video where reviewers disagree (reject vs accept, or different
  categories).

## 7. Download the video pool / command-line verdicts

```bash
# list items (no download)
python review_download.py --store feed_candidates_mine

# download all passing candidates into review_videos/ (re-runnable, skips existing)
python review_download.py --store feed_candidates_mine --download --status screened_candidate
# specific items: --status review  or  --code AbCd1234 (repeatable)

# verdicts from the command line (equivalent to the GUI)
python review_download.py --store feed_candidates_mine --approve CODE1 --reject CODE2
# category override when approving: --category travel_nature
```

## 8. Reports

```bash
python feed_collector.py --analyze-only --output feed_candidates_mine
open feed_candidates_mine/analysis.html
```

## 9. Update the tool from the branch

```bash
git pull fork review-toolchain
```

## Flag quick reference (feed_collector.py)

| Flag | Purpose | Default |
|---|---|---|
| `--target N` | NEW DISCOVERED Reels this run (not passing count) | 20 |
| `--delay S` | on-screen seconds per Reel during collection (uniform dwell) | 5 (min 1) |
| `--min-likes N` | minimum reported likes before screening (0 disables) | 10000 |
| `--max-seconds S` | video duration limit | 120 |
| `--frame-interval S` | seconds between sampled frames (higher = faster, coarser) | 2.0 |
| `--vision-batch N` | frames per vision-model call (0 = whole video in one call) | 1 |
| `--speech-model NAME` | faster-whisper model (base is faster on CPU) | small |
| `--workers N` | parallel items during --rescreen | 2 |
| `--llm on/off` | vision-model pre-screening during --rescreen | off (human-only) |
| `--output DIR` | dataset folder | feed_candidates |
| `--profile DIR` | browser login profile | instagram-session |
| `--channel NAME` | msedge / chrome / chromium | msedge |

Presets: strict = all defaults; fast = `--frame-interval 5 --vision-batch 0
--speech-model base --workers 3`; human-only = `--llm off` (the default:
every item goes to the review queue, the vision model never runs).

## Discipline

- One browser-using process at a time (Edge singleton profile).
- Ctrl+C is always a graceful stop; collection and rescreen both resume.
- Collection and rescreen are independent phases: collect first, screen any time.
