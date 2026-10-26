#!/usr/bin/env python3
"""review_team.py -- multi-user review sync for the reel-crawler toolchain.

Several lab members each collect reels on their own machine (and often their
own Instagram account). Every collected video must be reviewed once by EVERY
member, and every opinion is kept -- including conflicting ones. A private git
repo (the "sync repo") is the hub that makes this work:

  sync_repo/
    config.json            -- remote URL + auto-sync on/off          (committed)
    accounts/<name>.json   -- member account, salted pbkdf2 hash     (committed)
    items/<name>.jsonl     -- per-collector video metadata snapshots (committed)
    opinions/<name>.jsonl  -- per-reviewer decisions, one line each  (committed)
    .session.json          -- who is logged in on THIS machine       (NOT committed)
    pool.json              -- merged pool, derived from items/       (NOT committed)
    .gitignore             -- ignores the two files above

Why git instead of syncing the videos themselves:
  * GitHub caps files at 100 MB and repos at ~1 GB -- a reel collection can
    easily blow past that, while opinions are a few KB per reviewer.
  * Videos may contain third-party faces, which must stay local (IRB rule).
  * The videos are re-downloadable from their URLs whenever a reviewer needs
    to watch one (see review_download.py).

Only opinions + public metadata (URL, username, like count, caption, model
verdicts) ever leave the machine. No video, frame, or transcript is pushed.

Workflow:
  python review_team.py init <github-remote-url>   # once, on the first machine
  python review_team.py account add <name>         # once per member (prompts pw)
  python review_team.py login <name>               # once per machine
  python review_team.py sync pull                  # before reviewing
  ... collect (feed_collector.py) / review (review_gui.py) ...
  python review_team.py sync push                  # after reviewing/collecting
  python review_team.py status                     # everyone's progress
  python review_team.py disputes                   # videos reviewers disagree on
"""

import argparse
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SYNC = ROOT / 'sync_repo'

PBKDF2_ITERATIONS = 120_000


# --------------------------------------------------------------------------
# small utilities
# --------------------------------------------------------------------------

def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def code(url):
    """Shortcode of a reel URL, e.g. AbCd1234."""
    return re.sub(r'.*/reels?/([\w-]+)/?', r'\1', url)


def url_of(c):
    return f'https://www.instagram.com/reel/{c}/'


def jload(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:
        return None


def git_env():
    """Environment without this machine's dead proxy (127.0.0.1:10887)."""
    return {k: v for k, v in os.environ.items()
            if k.lower() not in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy')}


def git(args, check=True):
    """Run git inside the sync repo; raise RuntimeError on failure when check."""
    cmd = ['git', '-C', str(SYNC)] + list(args)
    r = subprocess.run(cmd, env=git_env(), capture_output=True, text=True)
    if check and r.returncode != 0:
        tail = (r.stderr or r.stdout or '').strip()[-800:]
        raise RuntimeError(tail or f"git {' '.join(args)} failed")
    return r


def _git_cfg(user):
    """Commit identity for this machine's session user."""
    git(['config', 'user.name', user], check=False)
    git(['config', 'user.email', f'{user}@reel-review.local'], check=False)


def config():
    return jload(SYNC / 'config.json') or {}


def _remote():
    r = git(['remote', 'get-url', 'origin'], check=False)
    return r.stdout.strip() if r.returncode == 0 else ''


# --------------------------------------------------------------------------
# session (who is logged in on this machine)
# --------------------------------------------------------------------------

def session_user():
    data = jload(SYNC / '.session.json')
    return data.get('name') if data else None


def require_session():
    name = session_user()
    if not name:
        sys.exit('Not logged in. Run: python review_team.py login <name>')
    return name


# --------------------------------------------------------------------------
# accounts (password -> salted pbkdf2 hash; the plaintext is never stored)
# --------------------------------------------------------------------------

def hash_password(pw, salt_hex=None):
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt, PBKDF2_ITERATIONS)
    return salt.hex(), digest.hex()


def verify_password(name, pw):
    data = jload(SYNC / 'accounts' / f'{name}.json')
    if not data:
        return False
    _, digest = hash_password(pw, data.get('salt'))
    return hmac.compare_digest(digest, data.get('hash', ''))


def accounts():
    d = SYNC / 'accounts'
    return sorted(p.stem for p in d.glob('*.json')) if d.is_dir() else []


def account_add(name, pw):
    """Create an account file. Returns nothing; raises on bad input."""
    if not re.fullmatch(r'[\w.-]{1,32}', name):
        raise ValueError('account name: letters, digits, dot, dash, underscore (max 32)')
    p = SYNC / 'accounts' / f'{name}.json'
    if p.exists():
        raise ValueError(f"account {name!r} already exists")
    if len(pw) < 4:
        raise ValueError('password must be at least 4 characters')
    salt, digest = hash_password(pw)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'name': name, 'salt': salt, 'hash': digest}, indent=2) + '\n',
                 encoding='utf-8')
    (SYNC / 'opinions').mkdir(exist_ok=True)
    (SYNC / 'items').mkdir(exist_ok=True)
    _git_cfg(session_user() or 'admin')
    git(['add', p.relative_to(SYNC).as_posix()])
    git(['commit', '-m', f'accounts: add {name}'])
    _push()


# --------------------------------------------------------------------------
# items: per-collector metadata snapshots of every local collection store
# --------------------------------------------------------------------------

def find_stores(root=None):
    """Every feed_candidates* folder holding a feed_collection.sqlite."""
    root = Path(root) if root is not None else ROOT
    out = []
    if root.is_dir():
        for d in sorted(root.glob('feed_candidates*')):
            if (d / 'feed_collection.sqlite').is_file():
                out.append(d)
    return out


def export_items(user, root=None):
    """Append unseen videos from every local store to items/<user>.jsonl.

    Only public metadata travels; audio transcripts, frames, and videos stay
    local. Returns True when at least one new item was written.
    """
    root = Path(root) if root is not None else ROOT
    fpath = SYNC / 'items' / f'{user}.jsonl'
    seen = set()
    if fpath.exists():
        for line in fpath.read_text(encoding='utf-8').splitlines():
            try:
                seen.add(json.loads(line).get('url'))
            except Exception:
                continue
    fresh = False
    fpath.parent.mkdir(parents=True, exist_ok=True)
    with fpath.open('a', encoding='utf-8') as f:
        for d in find_stores(root):
            try:
                db = sqlite3.connect(d / 'feed_collection.sqlite')
                db.row_factory = sqlite3.Row
                rows = [dict(r) for r in db.execute('SELECT * FROM feed_items').fetchall()]
                db.close()
            except Exception:
                continue
            for row in rows:
                url = row.get('url')
                if not url or url in seen:
                    continue
                try:
                    audio = json.loads(row.get('audio_json') or '{}') or {}
                except Exception:
                    audio = {}
                snap = {
                    'url': url,
                    'code': code(url),
                    'username': row.get('username'),
                    'likes': row.get('like_count'),
                    'caption': (row.get('caption') or '')[:200],
                    'duration_seconds': row.get('duration_seconds'),
                    'audio_status': audio.get('status'),
                    'model_status': row.get('status'),
                    'model_reason': row.get('reason'),
                    'model_category': row.get('category'),
                    'first_seen_utc': row.get('first_seen_utc'),
                    'store': d.name,
                    'collected_by': user,
                }
                f.write(json.dumps(snap, ensure_ascii=False) + '\n')
                seen.add(url)
                fresh = True
    return fresh


def merged_pool():
    """dict url -> item from every items/<name>.jsonl (later file wins)."""
    pool = {}
    d = SYNC / 'items'
    if d.is_dir():
        for p in sorted(d.glob('*.jsonl')):
            for line in p.read_text(encoding='utf-8').splitlines():
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if item.get('url'):
                    pool[item['url']] = item
    return pool


def refresh_pool():
    pool = merged_pool()
    (SYNC / 'pool.json').write_text(json.dumps(pool, ensure_ascii=False, indent=2) + '\n',
                                   encoding='utf-8')
    return pool


def pool():
    """Merged pool, rebuilt from items/ if pool.json is stale or absent."""
    cached = jload(SYNC / 'pool.json')
    if cached:
        return cached
    return refresh_pool() if SYNC.is_dir() else {}


# --------------------------------------------------------------------------
# opinions: one JSONL line per decision, every decision kept forever
# --------------------------------------------------------------------------

def opinions_for(user):
    p = SYNC / 'opinions' / f'{user}.jsonl'
    out = {}
    if p.exists():
        for line in p.read_text(encoding='utf-8').splitlines():
            try:
                op = json.loads(line)
            except Exception:
                continue
            if op.get('id'):
                out[op['id']] = op
    return out


def latest_opinions(user):
    """Latest decision per video URL (later decision on the same video wins)."""
    latest = {}
    for op in opinions_for(user).values():
        cur = latest.get(op['url'])
        if cur is None or op['utc'] >= cur['utc']:
            latest[op['url']] = op
    return latest


def record_opinion(user, url, action, category='', note='', **extra):
    """Append one review decision. Undo adds a tombstone line instead of deleting."""
    p = SYNC / 'opinions' / f'{user}.jsonl'
    p.parent.mkdir(parents=True, exist_ok=True)
    op = {
        'id': f"{user}-{int(time.time() * 1000)}-{secrets.token_hex(3)}",
        'user': user,
        'url': url,
        'code': code(url),
        'action': action,              # 'approve' | 'reject' | 'category'
        'category': category or '',
        'note': (note or '')[:300],
        'utc': now(),
    }
    op.update({k: v for k, v in extra.items() if v is not None})
    with p.open('a', encoding='utf-8') as f:
        f.write(json.dumps(op, ensure_ascii=False) + '\n')
    return op


def remove_opinion(user, op_id):
    """Drop one decision line (used by review_gui.py's undo)."""
    p = SYNC / 'opinions' / f'{user}.jsonl'
    if not p.exists():
        return False
    lines = p.read_text(encoding='utf-8').splitlines()
    keep = [l for l in lines if l.strip() and json.loads(l).get('id') != op_id]
    if len(keep) == len(lines):
        return False
    p.write_text('\n'.join(keep) + ('\n' if keep else ''), encoding='utf-8')
    return True


def reviewers():
    """Every member who has written at least one opinion."""
    d = SYNC / 'opinions'
    return sorted(p.stem for p in d.glob('*.jsonl')) if d.is_dir() else []


# --------------------------------------------------------------------------
# progress + disputes
# --------------------------------------------------------------------------

def progress(user, pool_dict=None):
    """(done, total, latest-opinions-dict) for one reviewer."""
    pool_dict = pool_dict if pool_dict is not None else pool()
    latest = latest_opinions(user)
    done = [u for u in pool_dict if u in latest]
    return len(done), len(pool_dict), latest


def dispute_rows(pool_dict=None):
    """Videos where reviewers disagree (reject vs accept, or category clash)."""
    pool_dict = pool_dict if pool_dict is not None else pool()
    rows = []
    users = reviewers()
    for url, item in sorted(pool_dict.items(), key=lambda kv: kv[0]):
        ops = [latest_opinions(u).get(url) for u in users]
        ops = [o for o in ops if o]
        if len(ops) < 2:
            continue
        acts = {o['action'] for o in ops}
        cats = {o['category'] for o in ops if o.get('category')}
        conflict = ('reject' in acts and len(acts) > 1) or len(cats) > 1
        if conflict:
            rows.append({'code': item.get('code') or code(url),
                         'url': url,
                         'username': item.get('username'),
                         'opinions': ops})
    return rows


# --------------------------------------------------------------------------
# sync: git pull / push with the proxy-stripped environment
# --------------------------------------------------------------------------

def sync_pull(quiet=False):
    """Pull team state from the remote; rebuild the local pool cache."""
    if not SYNC.is_dir() or not (SYNC / '.git').is_dir():
        raise RuntimeError('sync repo not initialized -- '
                           'run: python review_team.py init <remote-url>')
    r = git(['rev-parse', '--abbrev-ref', 'HEAD'], check=False)
    branch = r.stdout.strip() or 'main'
    try:
        git(['pull', '--rebase', 'origin', branch])
    except RuntimeError:
        # first-ever pull may not have an upstream yet (fresh empty remote).
        # Distinguish that from a real failure honestly.
        fetched = git(['fetch', 'origin'], check=False)
        probe = git(['rev-parse', '--verify', '--quiet', f'origin/{branch}'],
                    check=False)
        if probe.returncode != 0:
            if fetched.returncode != 0:
                raise RuntimeError('sync pull failed (network, credentials, '
                                   'or repo not found): '
                                   + (fetched.stderr or '').strip()[-200:])
            return  # remote exists but has nothing to pull yet
        try:
            git(['rebase', f'origin/{branch}'])
        except RuntimeError as rebase_exc:
            raise RuntimeError('sync pull failed: ' + str(rebase_exc)) from rebase_exc
    refresh_pool()
    if not quiet:
        print(f'Pulled latest team state -- pool has {len(pool())} videos.')


def sync_push(activity='review', quiet=False):
    """Commit this machine's changes (items/opinions/accounts) and push.

    Local collection stores are exported into items/ first, so every push
    (manual sync, review decision, end of a collection run) carries the
    newest collected metadata up to the shared repo. Videos/frames/audio
    stay local."""
    if not SYNC.is_dir() or not (SYNC / '.git').is_dir():
        raise RuntimeError('sync repo not initialized -- '
                           'run: python review_team.py init <remote-url>')
    user = session_user() or 'anonymous'
    _git_cfg(user)
    if user != 'anonymous':
        export_items(user)
    git(['add', '-A'])
    r = git(['status', '--porcelain'], check=False)
    if r.stdout.strip():
        git(['commit', '-m', f'{activity}: {user}'])
    if _remote():
        git(['pull', '--rebase', 'origin', 'main'], check=False)
        git(['push', 'origin', 'main'])
    refresh_pool()
    if not quiet:
        print('Synced team state to the shared repo.')


def _push():
    """Best-effort push used by account add (silent when no remote yet)."""
    if _remote():
        try:
            git(['pull', '--rebase', 'origin', 'main'], check=False)
            git(['push', 'origin', 'main'], check=False)
        except RuntimeError:
            pass


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def init_local(quiet=False):
    """Create the sync repo structure locally (no remote). Returns True if fresh."""
    if SYNC.is_dir():
        return False
    (SYNC / 'accounts').mkdir(parents=True, exist_ok=True)
    (SYNC / 'items').mkdir(exist_ok=True)
    (SYNC / 'opinions').mkdir(exist_ok=True)
    (SYNC / '.gitignore').write_text('.session.json\npool.json\n', encoding='utf-8')
    (SYNC / 'config.json').write_text(
        json.dumps({'remote': '', 'auto_sync': True}, indent=2) + '\n',
        encoding='utf-8')
    try:
        git(['init', '-b', 'main'])
    except RuntimeError:
        git(['init'])                      # git < 2.28
        git(['checkout', '-b', 'main'])
    _git_cfg('admin')
    git(['add', '-A'])
    git(['commit', '-m', 'init: reel review sync repo'])
    if not quiet:
        print(f'Initialized sync repo at {SYNC}')
    return True


def cmd_init(remote=None):
    if SYNC.is_dir():
        print(f'{SYNC} already exists -- not re-initializing.')
        return
    init_local()
    if remote:
        git(['remote', 'add', 'origin', remote])
        cfg = config()
        cfg['remote'] = remote
        (SYNC / 'config.json').write_text(json.dumps(cfg, indent=2) + '\n',
                                          encoding='utf-8')
        git(['add', 'config.json'])
        git(['commit', '-m', 'sync: set remote'], check=False)
        git(['push', '-u', 'origin', 'main'])
    print(f"Next: create accounts with 'python review_team.py account add <name>'.")


def cmd_account_add(name, pw=None):
    if not SYNC.is_dir():
        sys.exit('sync repo not initialized -- run: python review_team.py init <remote-url>')
    if pw is None:
        pw = getpass.getpass(f'Password for {name}: ')
        again = getpass.getpass('Repeat password: ')
        if pw != again:
            sys.exit('Passwords do not match.')
    try:
        account_add(name, pw)
    except ValueError as exc:
        sys.exit(f'Error: {exc}')
    print(f"Account {name!r} created and pushed. Tell them to run: "
          f"python review_team.py login {name}")


def cmd_account_list():
    for name in accounts():
        mark = ' (you)' if name == session_user() else ''
        print(name + mark)


def cmd_login(name, pw=None):
    if not SYNC.is_dir():
        sys.exit('sync repo not initialized -- run: python review_team.py init <remote-url>')
    if name not in accounts():
        sys.exit(f"Unknown account {name!r}. Existing: {', '.join(accounts()) or 'none'}")
    if pw is None:
        pw = getpass.getpass(f'Password for {name}: ')
    if not verify_password(name, pw):
        sys.exit('Wrong password.')
    (SYNC / '.session.json').write_text(
        json.dumps({'name': name, 'login_utc': now()}) + '\n', encoding='utf-8')
    print(f'Logged in as {name} on this machine.')
    if _remote():
        try:
            sync_pull(quiet=True)
            print('Pulled latest team state.')
        except RuntimeError as exc:
            print(f'  (could not pull yet: {exc})')


def cmd_logout():
    if (SYNC / '.session.json').exists():
        (SYNC / '.session.json').unlink()
        print('Logged out.')
    else:
        print('Nobody was logged in.')


def cmd_status():
    sync_pull(quiet=True)
    p = pool()
    names = sorted(set(accounts() + reviewers()))
    print(f'Pool: {len(p)} videos ({", ".join(d.name for d in find_stores()) or "no local stores"})')
    print(f"{'REVIEWER':<14}{'DONE':>6}{' / TOTAL':>9}{'PENDING':>9}")
    latest_by_user = {}
    for u in names:
        done, total, latest = progress(u, p)
        latest_by_user[u] = latest
        print(f'{u:<14}{done:>6}{("/" + str(total)):>9}{total - done:>9}')
    reviewed = set()
    for latest in latest_by_user.values():
        reviewed |= set(latest)
    pending = [item.get('code') or code(u) for u, item in sorted(p.items())
               if u not in reviewed]
    print(f'\nVideos nobody has reviewed yet: {len(pending)}')
    if pending:
        shown = pending[:40]
        print('  ' + ' '.join(shown) + (' ...' if len(pending) > 40 else ''))


def cmd_disputes():
    sync_pull(quiet=True)
    rows = dispute_rows()
    if not rows:
        print('No disputes -- every reviewed video has unanimous verdicts.')
        return
    print(f'{len(rows)} disputed video(s):\n')
    for r in rows:
        print(f"[{r['code']}]  @{r['username'] or '?'}  {r['url']}")
        for op in sorted(r['opinions'], key=lambda o: o['utc']):
            print(f"    {op['user']:<12} {op['action']:<9} {op.get('category') or '':<20} {op['utc']}")
        print()


def cmd_pool():
    sync_pull(quiet=True)
    print(json.dumps(pool(), ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    sp = sub.add_parser('init', help='create the local sync repo, optionally wired to a GitHub remote')
    sp.add_argument('remote', nargs='?', default=None)

    sp = sub.add_parser('account', help='manage member accounts')
    asp = sp.add_subparsers(dest='account_cmd', required=True)
    a = asp.add_parser('add', help='create a new member account (prompts for a password)')
    a.add_argument('name')
    asp.add_parser('list', help='list member accounts')

    sp = sub.add_parser('login', help='log in as an existing member on this machine')
    sp.add_argument('name')

    sub.add_parser('logout', help='log out of this machine')

    sp = sub.add_parser('sync', help='pull or push team state to the shared repo')
    ssp = sp.add_subparsers(dest='sync_cmd', required=True)
    ssp.add_parser('pull', help="download everyone else's items and reviews")
    ssp.add_parser('push', help='upload my items and reviews')

    sub.add_parser('status', help="everyone's review progress")
    sub.add_parser('disputes', help='videos reviewers disagree on (table)')
    sub.add_parser('pool', help='print the merged video pool as JSON')
    sub.add_parser('gui', help='open the browser-based team hub (team_gui.py): '
                               'setup, accounts, login, sync, progress')
    args = ap.parse_args()

    try:
        if args.cmd == 'init':
            cmd_init(args.remote)
        elif args.cmd == 'account':
            if args.account_cmd == 'add':
                cmd_account_add(args.name)
            else:
                cmd_account_list()
        elif args.cmd == 'login':
            cmd_login(args.name)
        elif args.cmd == 'logout':
            cmd_logout()
        elif args.cmd == 'sync':
            if args.sync_cmd == 'pull':
                sync_pull()
            else:
                sync_push()
        elif args.cmd == 'status':
            cmd_status()
        elif args.cmd == 'disputes':
            cmd_disputes()
        elif args.cmd == 'pool':
            cmd_pool()
        elif args.cmd == 'gui':
            subprocess.Popen([sys.executable, str(ROOT / 'team_gui.py')],
                             cwd=str(ROOT), start_new_session=True)
            print('Team hub opened in your browser (team_gui.py).')
    except RuntimeError as exc:
        sys.exit(f'Error: {exc}')
    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == '__main__':
    main()
