# reel-crawler · Team Review Tutorial

> 中文版：[TEAM-TUTORIAL.zh-CN.md](TEAM-TUTORIAL.zh-CN.md)

Everything the lab needs to collect Instagram reels, screen them, and have
**every member review every video** — with all opinions kept and synced
through one private GitHub repo.

- **New to the team?** Start at [2. What you need](#2-what-you-need), then follow
  [4. Adding your machine](#4-adding-your-machine).
- **Just reviewing today?** Jump to [5. Daily loop](#5-daily-loop---review).
- **Prefer the command line?** Every GUI action has a CLI equivalent —
  see [6. Command-line reference](#6-command-line-reference).

---

## 1. How the team workflow fits together

```
collect                screen (optional, per lab policy)         review
──────────             ──────────────────────────────            ──────
feed_collector.py  →   feed_collector.py --rescreen (LLM)    →   review_gui.py
one member per         like-gate + audio + vision model          EVERY member
Instagram account                                                 reviews EVERY video
        │                                                              │
        └──────────────  sync_repo/ (private GitHub repo)  ────────────┘
                          items/  opinions/  accounts/
```

- **Items** = the public metadata of every collected reel (URL, @author, like
  count, caption, model verdicts). Videos, frames, and transcripts never
  leave the machine — IRB rule (videos may contain third-party faces).
- **Opinions** = one append-only log per reviewer. Every decision is kept
  forever, including conflicting ones; disputes are listed automatically.
- **Accounts** = each member's username + password (salted PBKDF2 hash only).
  The whole team can share **one GitHub account** for the repo — members are
  told apart by their in-app account, and every git commit is authored with
  that account name. No per-member GitHub collaborators needed.

## 2. What you need

| Requirement | Notes |
|---|---|
| Python 3 | the review tools use only the standard library |
| git | ships with macOS (Xcode CLT) / any Linux distro |
| A browser | the tool pages are local web pages (Edge/Chrome) |
| A **private** GitHub repo | created once (section 3); owned by any single account (e.g. the lab account) |

Only machines that **collect and screen** additionally need the collector's
dependencies (Playwright + cookies, and Ollama for the vision model) — see
RUNBOOK.md for that part. Reviewing needs nothing extra.

## 3. One-time setup (first machine — ~5 minutes)

### 3.1 Create the private repo on GitHub

1. Log in to the account that will own the sync repo (one lab account is fine).
2. **New repository** → name it e.g. `reel-review-sync` → **Private** →
   leave "Add a README" unchecked (the repo must start empty) → Create.
3. (Shared-account route) Create a **token** for it: Settings → Developer
   settings → Personal access tokens → scopes: `repo` only. Copy the token —
   it is pasted once per machine and then never shown again.
   (Your-own-credentials route: skip the token and use each machine's own
   GitHub access, e.g. SSH. Both routes work.)

### 3.2 Start the team hub on the first machine

```bash
cd reel-crawler
python3 team_gui.py        # or: python3 review_team.py gui
```

Your browser opens **http://127.0.0.1:8766** — the team hub. Fill the five
cards top to bottom:

**1 · Shared GitHub repo**
Paste the repo URL (`https://github.com/<account>/reel-review-sync`) and, if
you use the shared-account route, the token. Click **Set up / update remote**.
This creates the local `sync_repo/` folder, commits the first state, and
pushes it to GitHub.

**2 · Member accounts**
Create one account per member: username + password (≥ 4 characters). Passwords
are stored only as salted PBKDF2 hashes and synced to GitHub as hashes —
plaintext never leaves the machine. The table shows everyone's review counts.

**3 · Log in on this machine**
Log in with your own account. If "Open the review queue right after login" is
checked, the review page (http://127.0.0.1:8765) opens automatically. The
checkbox only appears on the login form — once you are logged in, card 3
shows an **Open review queue →** button instead (same effect), and the page
header keeps the same button at all times. If your browser blocks the
automatic pop-up, just click that button — the manual link always works.

That is the entire setup. The other cards are used every day (section 5).

## 4. Adding your machine

Every member gets the toolchain code (the repo that contains this file) on
their own machine, then:

```bash
cd reel-crawler
python3 team_gui.py
```

1. **Card 1** — paste the same repo URL (and token, if the shared-account
   route is used). The hub detects that the repo already has history and
   **clones it automatically** instead of creating a new one.
2. **Card 3** — log in with **your own** account and password.

Nothing else is needed: your review queue is the whole pool minus what you
have already reviewed.

## 5. Daily loop — review

```bash
python3 team_gui.py            # the hub opens
```

- **Card 4 · Sync** — click **Sync: online → this machine** before you start
  (login does this automatically) so you see everything collected and
  reviewed since yesterday. **Sync: this machine → online** uploads your
  changes.
- **Card 3** — click **Open review queue** (or log in with the checkbox).
- In the review queue, keyboard only:

  | Key | Action |
  |---|---|
  | `g` | approve the video (keep the model's category) |
  | `w` | reject the video |
  | `r` | choose a category (keys `1`–`12`) and approve |
  | `u` | undo the last decision |
  | `←`/`→` | focus the frame evidence |

  Every decision is **pushed to GitHub immediately** — no manual push needed.
  Items without local frame evidence still appear; open the reel link and
  decide from the video itself.
- When the queue is empty, you have reviewed the entire pool. Progress is
  visible to everyone in card 2 and via `python3 review_team.py status`.

### Collecting on the same machine (optional)

If you also collect with an Instagram account, run the collector as usual —
`python3 feed_collector.py ...` — and your new videos are pushed to the pool
automatically when the run finishes. See RUNBOOK.md for the collector/screening
workflow.

## 6. Command-line reference

The hub is a GUI over `review_team.py`; everything is also available in the
terminal (scriptable, useful over SSH):

| Task | Command |
|---|---|
| Initialize sync repo (first machine) | `python3 review_team.py init https://github.com/<account>/reel-review-sync` |
| Join from another machine | `git clone <repo-url> sync_repo` |
| Create an account | `python3 review_team.py account add <name>` |
| List accounts | `python3 review_team.py account list` |
| Log in / out | `python3 review_team.py login <name>` · `logout` |
| Pull / push team state | `python3 review_team.py sync pull` · `sync push` |
| Everyone's progress | `python3 review_team.py status` |
| Disputed videos (table) | `python3 review_team.py disputes` |
| Print the merged pool | `python3 review_team.py pool` |
| Open the team hub | `python3 review_team.py gui` |
| Review queue (team mode) | `python3 review_gui.py` |

## 7. Accounts & passwords

- Username: letters, digits, dot, dash, underscore (max 32).
- Password: at least 4 characters. Stored as salted PBKDF2-SHA256
  (120 000 iterations) in `sync_repo/accounts/<name>.json` — only the hash
  is ever written or synced.
- To change your password: team hub → card 3 → **Change my password**.
- No account deletion is offered on purpose: deleting an account would orphan
  that member's opinions. Ask the toolchain maintainer instead.

## 8. Progress, disputes, and data

- **Progress**: card 2 in the hub, or `status`. `done / total` per member,
  plus how many videos nobody has reviewed yet.
- **Disputes**: card 5 in the hub, or `disputes`. A video is disputed when
  reviewers disagree — accept vs reject, or different categories. All
  opinions remain in the files; the table just surfaces the conflict.
- **Where things live**:

  | Path | Contents |
  |---|---|
  | `sync_repo/accounts/` | member accounts (hashes only) |
  | `sync_repo/items/<name>.jsonl` | per-collector video metadata |
  | `sync_repo/opinions/<name>.jsonl` | per-reviewer decisions, append-only |
  | `sync_repo/pool.json` | merged pool (derived, not committed) |
  | `sync_repo/.session.json` | who is logged in on this machine (not committed) |
  | `feed_candidates*/` | local collection stores (never committed) |
  | `review_frames/`, `review_videos/` | local frame evidence / downloads (never committed) |

## 9. FAQ

**The setup button said "could not reach the remote"**
Wrong token, wrong URL, or no network. Token scopes must include `repo`;
the URL must be exact (case-sensitive), and the machine must reach GitHub
(no VPN/proxy blocking — the tool already strips stale proxy variables).

**Login says "could not pull yet"**
The machine cannot reach GitHub. Reviewing works offline — decisions are
written locally and pushed the next time a pull/push succeeds (the review
queue retries the push on every decision).

**Two people push at the same time**
Every push pulls with rebase first; a conflicting push fails and is retried
on the next decision. The worst case is re-running one decision — opinions
are append-only, so nothing is lost.

**I reviewed a video but it shows as unreviewed**
Run **Sync · pull** — the hub shows local state; pull refreshes it with
everyone's latest pushes.

**Do I need to be a GitHub collaborator on the sync repo?**
No — with the shared-account route, everyone pushes with the same token;
with the SSH route, add each machine's key to that GitHub account. Either
way the repo needs only **one** GitHub account.

**Can I use this without any GitHub account?**
Yes, but syncing is then manual: `sync_repo/` is just a git repo. Push/pull
to any git host (GitLab, a lab server, a USB drive) works identically —
only the URL changes.
