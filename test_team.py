#!/usr/bin/env python3
"""Offline tests for review_team.py (stdlib only -- no network, local git only)."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_team as rt


def make_store(path):
    """A feed_candidates*-style store with the columns review_team reads."""
    d = Path(path)
    d.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(d / 'feed_collection.sqlite')
    db.execute('''CREATE TABLE IF NOT EXISTS feed_items (
        url TEXT, username TEXT, like_count INTEGER, caption TEXT,
        duration_seconds REAL, audio_json TEXT, status TEXT, reason TEXT,
        category TEXT, first_seen_utc TEXT)''')
    db.commit()
    return db


class TeamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        rt.SYNC = self.root / 'sync_repo'
        rt.ROOT = self.root

    def tearDown(self):
        self.tmp.cleanup()

    def test_password_hashing(self):
        rt.SYNC.mkdir(parents=True)
        (rt.SYNC / 'accounts').mkdir()
        salt, digest = rt.hash_password('hunter2secret')
        (rt.SYNC / 'accounts' / 'alice.json').write_text(
            json.dumps({'name': 'alice', 'salt': salt, 'hash': digest}))
        self.assertTrue(rt.verify_password('alice', 'hunter2secret'))
        self.assertFalse(rt.verify_password('alice', 'wrong'))
        self.assertFalse(rt.verify_password('bob', 'hunter2secret'))

    def test_full_team_flow(self):
        # 1. init the hub (no remote yet) + create an account + log in
        rt.cmd_init(None)
        self.assertTrue((rt.SYNC / '.git').is_dir())
        rt.cmd_account_add('alice', 'alice-pass-1')
        rt.cmd_login('alice', 'alice-pass-1')
        self.assertEqual(rt.session_user(), 'alice')

        # 2. export local stores; duplicates are skipped
        db = make_store(self.root / 'feed_candidates_mine')
        url = 'https://www.instagram.com/reel/TestAbc12/'
        db.execute('INSERT INTO feed_items VALUES (?,?,?,?,?,?,?,?,?,?)',
                   (url, 'some_user', 45000, 'caption here', 15.0,
                    '{"status":"english"}', 'review', 'not_screened',
                    'other', '2026-10-20T00:00:00Z'))
        db.commit(); db.close()
        self.assertTrue(rt.export_items('alice'))
        self.assertFalse(rt.export_items('alice'))       # no new items
        self.assertIn(url, rt.merged_pool())

        # 3. opinions + progress + disputes (offline, no remote)
        rt.record_opinion('alice', url, 'approve', 'travel_nature')
        self.assertEqual(rt.progress('alice')[0], 1)
        self.assertEqual(len(rt.dispute_rows()), 0)      # single reviewer: no dispute
        rt.record_opinion('bob', url, 'reject')
        self.assertEqual(len(rt.dispute_rows()), 1)      # approve vs reject
        rt.record_opinion('alice', url, 'category', 'comedy')
        self.assertEqual(rt.latest_opinions('alice')[url]['action'], 'category')
        op_id = list(rt.opinions_for('alice'))[0]
        self.assertTrue(rt.remove_opinion('alice', op_id))
        self.assertFalse(rt.remove_opinion('alice', 'nope'))

        # 4. git round trip through a local bare repo (HEAD must point at
        # main, like GitHub's default, or clones cannot checkout anything)
        bare = self.root / 'hub.git'
        subprocess.run(['git', 'init', '--bare', '-b', 'main', str(bare)],
                       check=True, capture_output=True)
        rt.git(['remote', 'add', 'origin', str(bare)])
        rt.sync_push('review', quiet=True)               # commit + first push
        machine2 = self.root / 'machine2'
        subprocess.run(['git', 'clone', str(bare), str(machine2)],
                       check=True, capture_output=True)
        rt.SYNC = machine2
        rt.cmd_login('alice', 'alice-pass-1')            # works from the clone
        rt.record_opinion('alice', url, 'approve')
        rt.sync_push('review', quiet=True)
        rt.SYNC = self.root / 'sync_repo'
        rt.sync_pull(quiet=True)
        self.assertIn(url, rt.latest_opinions('alice'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
