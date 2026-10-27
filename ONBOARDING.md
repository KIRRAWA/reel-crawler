# Onboarding bulletin — one-minute start for new reviewers

**What you need** — Python 3, git, and four items from your lab admin:


1. The tool ZIP (`review-toolchain` branch) from the lab's GitHub page 
(https://github.com/KIRRAWA/reel-crawler) Download from the review tool chain
2. The sync repo URL (Will be posted in General in Slack)
3. The shared GitHub token (Will be posted in General in Slack, is a passcode 
to modify our lab data, should be kept within our lab)
4. Your in-app account + password (You create it by yourself when needed in the app)

**Five steps**
(The following cd and run steps should be performed in your terminal)
1. Unzip the tool ZIP and `cd` into it (the folder name carries a
   `-review-toolchain` suffix).
2. Run `python3 team_gui.py` — the hub opens at http://127.0.0.1:8766.
3. In the web page window that automatically opens, paste the sync repo URL and the 
   shared token. The hub clones the repo automatically. The token is saved in a
   local hidden file on this machine only, never shown again.
4. log in with your own in-app account (or create one) (not a GitHub account).
5. Click **Open review queue** → start reviewing.

**While reviewing** — it works like an online exam

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
- Found reels the team should review? Add them in the hub (card 6: paste
  links, one per line), or find new ones with the collector — both are
  covered in [TEAM-TUTORIAL.md](TEAM-TUTORIAL.md) §5.
- Details and edge cases: [TEAM-TUTORIAL.md](TEAM-TUTORIAL.md).

**Windows notes**

- Use `python team_gui.py` (not `python3`). Install Python from python.org
  with "Add Python to PATH" checked, and install Git for Windows.
- Keep the tool folder OUT of synced or watched folders (OneDrive, Dropbox,
  or the Claude Desktop files folder). Sync engines, antivirus, and indexers
  lock `.git/objects` files mid-operation, which makes setup fail with
  "WinError 5 access denied" and then "not a git repository".
- If a failed setup leaves a `sync_repo` folder behind, delete it (Explorer,
  or `rmdir /s /q sync_repo` in cmd) and retry.
