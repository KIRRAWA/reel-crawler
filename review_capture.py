#!/usr/bin/env python3
"""review_capture.py -- save lightweight frame evidence for review items.

Every reel gets a FIXED set of frames (--n, default 10), spread evenly
across the video duration -- the same treatment for every video. Frames are
saved as small 320px JPEGs under review_frames/<shortcode>/ together with a
meta.json (caption, transcript, audio status) that review_gui.py renders.

Three ways to run it:

  python review_capture.py --store feed_candidates_mine
      # every 'review' item in one collection store

  python review_capture.py --pool
      # every team pool video that has no frames yet (sync repo + login)

  python review_capture.py --url https://www.instagram.com/reel/AbCd1234/
      # one reel by link -- the same function behind the review page's
      # "Capture 10 frames from link" button

The link-based capture uses the saved cookie jar (cookies.txt), so no
browser is launched at all when the jar exists. Batch modes over a store
prefer the jar too and only fall back to a headless browser export.
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import review_download as rd

INTERVAL = 2.0  # nominal screening frame interval (used to map frames to model votes)


def shortcode(url):
    m = re.search(r'/reels?/([\w-]+)/?', url)
    return m.group(1) if m else ''


def clean(v):
    """A verdict is 'clean' when nothing would send the video to review."""
    return (v.get('political') == 'no' and v.get('sensitive') == 'no'
            and v.get('meaningful_text_language') in ('english', 'none')
            and v.get('us_audience_context') == 'suitable'
            and (v.get('confidence') or 0) >= 0.8)


def download_video(url, folder):
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
        f.write('\n'.join(rd.export_cookies()) + '\n')
        cookie_path = f.name
    # Strip dead proxy env vars (this machine's 127.0.0.1:10887).
    env = {k: v for k, v in os.environ.items()
           if k.lower() not in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy')}
    try:
        cmd = ['yt-dlp', '--no-update', '--no-warnings', '--no-playlist',
               '--cookies', cookie_path,
               '-f', 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b',
               '-o', str(Path(folder) / 'video.%(ext)s'),
               '--print', 'after_move:filepath', url]
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not r.stdout.strip():
            raise RuntimeError((r.stderr or 'download failed').strip().splitlines()[-1])
        return Path(r.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(cookie_path)


def collect_frames_even(path, out_dir, n):
    """Decode the video and save n frames evenly spread across its duration.

    Target times are the midpoints of n equal segments, so every part of the
    video is represented. Returns (duration_seconds, saved_frames)."""
    import av
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type == 'video'), None)
        if stream is None:
            raise RuntimeError('No video stream')
        duration = (float(stream.duration * stream.time_base)
                    if stream.duration else None)
        if not duration:
            duration = 0.0
            for frame in container.decode(video=0):
                duration = float(frame.time or 0)
        if not duration or duration <= 0:
            raise RuntimeError('Cannot determine video duration')
        targets = [duration * (i + 0.5) / n for i in range(n)]
        saved, next_i = [], 0
        for frame in container.decode(video=0):
            at = float(frame.time or 0)
            if next_i < n and at >= targets[next_i]:
                name = f'f{next_i:03d}.jpg'
                im = frame.to_image()
                im.thumbnail((320, 320))
                im.save(Path(out_dir) / name, quality=70)
                saved.append({'idx': next_i, 'file': name, 'time': round(at, 1)})
                next_i += 1
    if not saved:
        raise RuntimeError('No frames decoded')
    return round(duration, 1), saved


def capture_link(url, frames_dir='review_frames', n=10, force=False):
    """Download one reel by its link and save n evenly spaced frames.

    This is the function behind the review page's 'Capture 10 frames from
    link' button. Returns the number of frames saved (0 when frames already
    exist and force is off). Raises RuntimeError on download/decode failure.
    """
    code = shortcode(url)
    if not code:
        raise RuntimeError(f'not a reel URL: {url}')
    out_dir = Path(frames_dir) / code
    if (out_dir / 'meta.json').exists() and not force:
        return 0    # already captured -- nothing to do
    with tempfile.TemporaryDirectory(prefix='review-cap-') as folder:
        path = download_video(url, folder)
        duration, saved = collect_frames_even(path, out_dir, n)
    meta = {
        'url': url, 'username': '', 'caption': '', 'likes': None,
        'status': 'review', 'reason': 'frames_from_link', 'category': 'other',
        'audio_status': None, 'transcript': '', 'duration_seconds': duration,
        'frames': saved,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                       encoding='utf-8')
    return len(saved)


def model_vote(visuals, idx):
    for v in visuals:
        s = int(v.get('sample_batch_start_index', 0))
        n = int(v.get('sample_frame_count', 0))
        if s <= idx < s + n:
            return v
    return None


def capture_row(row, args):
    code = shortcode(row['url'])
    out_dir = Path(args.frames) / code
    if (out_dir / 'meta.json').exists() and not args.force:
        print(f'{code}: already captured, skipping (--force to redo)')
        return
    visuals = json.loads(row['visual_json'] or '[]')
    print(f'{code}: downloading video...')
    with tempfile.TemporaryDirectory(prefix='review-cap-') as folder:
        try:
            path = download_video(row['url'], folder)
        except Exception as exc:
            print(f'{code}: DOWNLOAD FAILED ({exc}) -- skipping')
            return
        try:
            duration, saved = collect_frames_even(path, out_dir, args.n)
        except Exception as exc:
            print(f'{code}: DECODE FAILED ({exc}) -- skipping')
            return
    audio = json.loads(row['audio_json'] or '{}')

    def tag(f):
        # Keep the per-frame model audit where the screening run left one.
        vote = model_vote(visuals, int(f['time'] / INTERVAL))
        return dict(f, flagged=vote is not None and not clean(vote),
                    model=vote if vote else None)

    meta = {
        'url': row['url'], 'username': row['username'], 'caption': row['caption'],
        'likes': row['like_count'], 'status': row['status'], 'reason': row['reason'],
        'category': row['category'], 'audio_status': audio.get('status'),
        'transcript': audio.get('transcript', ''),
        'duration_seconds': row.get('duration_seconds') or duration,
        'frames': [tag(f) for f in saved],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                       encoding='utf-8')
    print(f'{code}: saved {len(saved)} frames -> {out_dir}')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--store', default='feed_candidates_mine', help='collection folder')
    ap.add_argument('--frames', default='review_frames', help='evidence output dir')
    ap.add_argument('--n', type=int, default=10,
                    help='frames per video, evenly spread across its duration (default 10)')
    ap.add_argument('--url', default=None, help='capture one reel by link instead of a batch')
    ap.add_argument('--pool', action='store_true',
                    help='capture every team pool video (needs sync repo + login)')
    ap.add_argument('--only', action='append', default=[], metavar='CODE',
                    help='shortcode to capture (repeatable)')
    ap.add_argument('--force', action='store_true', help='re-capture items that already have frames')
    args = ap.parse_args()

    if args.url:
        code = shortcode(args.url)
        n = capture_link(args.url, args.frames, args.n, args.force)
        print(f'{code}: {n} frame(s) saved -> {Path(args.frames) / code}')
        return

    if args.pool:
        import review_team as rt
        user = rt.session_user()
        if not user:
            sys.exit('Not logged in -- run: python review_team.py login <name>')
        pool = rt.pool()
        rows = [{'url': u, 'username': pool[u].get('username'),
                 'caption': pool[u].get('caption'), 'like_count': pool[u].get('likes'),
                 'status': pool[u].get('model_status') or 'review',
                 'reason': pool[u].get('model_reason') or 'no_frame_evidence',
                 'category': pool[u].get('model_category') or 'other',
                 'audio_json': '{}', 'visual_json': '[]',
                 'duration_seconds': pool[u].get('duration_seconds')}
                for u in sorted(pool)]
    else:
        db = sqlite3.connect(Path(args.store) / 'feed_collection.sqlite')
        db.row_factory = sqlite3.Row
        q = "SELECT * FROM feed_items WHERE status='review'"
        params = []
        if args.only:
            q += ' AND url IN (' + ','.join('?' * len(args.only)) + ')'
            params += [f'https://www.instagram.com/reel/{c}/' for c in args.only]
        rows = [dict(r) for r in db.execute(q + ' ORDER BY first_seen_utc', params)]
        db.close()
    print(f'{len(rows)} item(s) to capture ({args.n} frames each).')
    for row in rows:
        capture_row(row, args)
    print('Done. Start the review queue with: python review_gui.py')


if __name__ == '__main__':
    main()
