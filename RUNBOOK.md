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

## 6. Human review (optional, recommended)

```bash
# capture uncertain-frame evidence first (zero model calls)
python review_capture.py --store feed_candidates_mine --frames review_frames
# only some items: --only CODE1 --only CODE2 ; re-capture: --force

# keyboard review queue at http://127.0.0.1:8765
python review_gui.py --store feed_candidates_mine --frames review_frames
# keys: g approve · w reject · r choose category (1-12) · u undo · arrows focus frames
```

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
| `--output DIR` | dataset folder | feed_candidates |
| `--profile DIR` | browser login profile | instagram-session |
| `--channel NAME` | msedge / chrome / chromium | msedge |

Presets: strict = all defaults; fast = `--frame-interval 5 --vision-batch 0
--speech-model base --workers 3`.

## Discipline

- One browser-using process at a time (Edge singleton profile).
- Ctrl+C is always a graceful stop; collection and rescreen both resume.
- Collection and rescreen are independent phases: collect first, screen any time.
