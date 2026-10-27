# Onboarding bulletin — one-minute start for reviewers

**What you need** — Python 3, git, and four items from your lab admin:

| Item | Where it comes from |
|---|---|
| The tool ZIP (`review-toolchain` branch) | the lab's GitHub link |
| The sync repo URL (private) | the lab admin |
| The shared GitHub token | the lab admin (pasted once per machine) |
| Your in-app account + password | created by the lab admin |

No GitHub account of your own. No Playwright, no Ollama, no other
dependencies — reviewing uses only the Python standard library.

**Five steps**

1. Unzip the tool ZIP and `cd` into it (the folder name carries a
   `-review-toolchain` suffix).
2. Run `python3 team_gui.py` — the hub opens at http://127.0.0.1:8766.
3. **Card 1 · Shared GitHub repo** — paste the sync repo URL and the shared
   token. The hub clones the repo automatically. The token is saved in a
   local hidden file on this machine only, never shown again.
4. **Card 3 · Log in on this machine** — log in with **your own in-app
   account** (not a GitHub account).
5. Click **Open review queue** → start reviewing.

**While reviewing** — it works like an exam paper:

| Key | Action |
|---|---|
| `g` | approve (keep the model's category) |
| `w` | reject |
| `r` | choose a category (`1`–`12`) and approve |
| `p` / `n`, `↑` / `↓` | previous / next video (wraps around at the ends) |
| `s` | submit all decisions at once |
| `u` | undo the last decision |

- Decisions stay local until you press `s` — then they sync to the shared
  repo and your progress is visible to the whole team.
- Items without local frames: open the reel link and decide from the video
  itself.
- Details and edge cases: [TEAM-TUTORIAL.md](TEAM-TUTORIAL.md).
