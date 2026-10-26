#!/usr/bin/env python3
"""review_gui.py -- keyboard-driven human review of the screening queue.

Serves a local page listing every review item that has frame evidence
(prepared by review_capture.py). Keyboard:
  g      approve the item (keep the model's category)
  w      reject the item (excluded)
  r      choose a category (keys 1-12 or click) and approve with it
  u      undo the last decision
  <- / -> move frame focus
  p / n  previous / next video (walks the whole list, like an exam)
  s      submit: upload all decisions to the shared repo in one go
Decisions are written back into <store>/feed_collection.sqlite (the model's
original verdict is preserved inside the new reason for audit) and the CSVs
plus analysis.html are regenerated after every decision.

Items without captured frames still appear, so you can open the reel link
and decide from the video itself.

Team mode (review_team.py): when a sync repo exists and someone is logged
in, the queue becomes the merged pool minus your own opinions. The page
shows a sidebar with your answered and unanswered videos, lets you jump
back and change earlier decisions, and uploads everything to the shared
repo only when you press Submit (s) -- exam style. Changing an earlier
decision appends a new line (latest wins), so nothing is ever lost.
"""

import argparse
import json
import re
import sqlite3
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import feed_collector as f
import review_team as rt

STATE = {'store': 'feed_candidates_mine', 'frames': 'review_frames', 'undo': [],
         'team_user': None, 'draft': set()}

PAGE = '''<!doctype html>
<html><head><meta charset="utf-8"><title>Reel review queue</title>
<style>
body{font:15px/1.5 system-ui;margin:0;background:#f4f6fa;color:#1c2330}
header{padding:14px 22px;background:#fff;border-bottom:1px solid #e2e8f0;display:flex;gap:18px;align-items:baseline;flex-wrap:wrap}
header .code{font:700 19px ui-monospace,monospace}
header .muted{color:#5b6b80}
#meta{padding:14px 22px;background:#fff;border-bottom:1px solid #e2e8f0}
#meta .reason{color:#a33}
#meta .transcript{max-height:120px;overflow:auto;background:#f0f3f8;padding:8px 12px;border-radius:8px;white-space:pre-wrap;margin-top:8px;font-size:13px}
#frames{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;padding:18px 22px}
.card{background:#fff;border:1px solid #dde4ee;border-radius:10px;overflow:hidden;cursor:pointer}
.card img{width:100%;display:block;aspect-ratio:1/1;object-fit:cover}
.card .info{padding:6px 10px;font-size:12px;color:#5b6b80}
.card.sel{outline:3px solid #2f6fed;outline-offset:2px}
.card.flagged{border-color:#e06c4f;box-shadow:inset 0 0 0 1px #e06c4f}
.tag{display:inline-block;background:#e06c4f;color:#fff;border-radius:4px;padding:0 5px;margin-right:4px;font-size:11px}
#help{position:fixed;bottom:0;left:0;right:0;background:#101826;color:#cfd8e6;padding:10px 22px;font-size:13px;z-index:9}
kbd{background:#243040;border-radius:4px;padding:1px 7px;margin:0 2px}
#modal{position:fixed;inset:0;background:rgba(15,23,42,.55);display:flex;align-items:center;justify-content:center;z-index:10}
#modal.hidden{display:none}
#modalbox{background:#fff;border-radius:12px;padding:18px 22px;max-width:640px}
#modalbox .cats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
#modalbox button{padding:10px;font-size:14px;border:1px solid #cfd8e6;border-radius:8px;background:#f7f9fc;cursor:pointer}
#modalbox button:hover{background:#e8f0fe}
.done{padding:40px;text-align:center;font-size:18px}
/* exam-style sidebar */
#side{position:fixed;top:0;bottom:52px;left:0;width:280px;background:#fff;border-right:1px solid #e2e8f0;overflow-y:auto;z-index:8;display:flex;flex-direction:column}
#side.hidden{display:none}
#side .sidehead{padding:14px 14px 10px;border-bottom:1px solid #eef2f8}
#side .sidehead .t{font-weight:700;font-size:14px}
#side .sidehead .m{font-size:12px;color:#5b6b80;margin-top:2px}
#btn-submit{display:block;width:100%;background:#1a7f37;color:#fff;border:none;border-radius:8px;padding:10px;font:600 14px system-ui;cursor:pointer;margin-top:10px}
#btn-submit:disabled{opacity:.55;cursor:default}
#side-submsg{margin-top:8px;font-size:12px;min-height:16px}
#side .sec{font-size:12px;font-weight:700;color:#5b6b80;padding:10px 14px 4px;letter-spacing:.4px}
.selist{padding:0 8px 8px;flex-shrink:0}
.se{display:flex;gap:8px;align-items:center;padding:6px 8px;border-radius:8px;cursor:pointer;font-size:13px}
.se:hover{background:#f0f4fa}
.se.cur{background:#e8f0fe;outline:1px solid #2f6fed}
.se .c{font:600 12px ui-monospace,monospace;color:#1c2330}
.se .v{flex:1;text-align:right;font-size:11px;color:#5b6b80;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.se .v.pass{color:#1a7f37}
.se .v.rej{color:#b3261e}
.se .dot{width:8px;height:8px;border-radius:50%;background:#e8890c;flex-shrink:0}
.sidefoot{border-top:1px solid #eef2f8;padding:10px 14px;display:flex;gap:8px}
.sidefoot button{flex:1;padding:8px;font:600 13px system-ui;border:1px solid #c6d2e2;border-radius:8px;background:#f7f9fc;cursor:pointer}
#mainwrap{margin-left:280px}
body.no-side #mainwrap{margin-left:0}
body.no-side #side{display:none}
</style></head>
<body>
<div id="side">
 <div class="sidehead">
  <div class="t">Review list</div>
  <div class="m" id="side-prog"></div>
  <button id="btn-submit">Submit all decisions</button>
  <div id="side-submsg"></div>
 </div>
 <div class="sec">Not decided yet (<span id="n-pending">0</span>)</div>
 <div class="selist" id="list-pending"></div>
 <div class="sec">Decided (<span id="n-decided">0</span>)</div>
 <div class="selist" id="list-decided"></div>
 <div style="flex:1"></div>
 <div class="sidefoot">
  <button id="btn-prev">← Prev</button>
  <button id="btn-next">Next →</button>
 </div>
</div>
<div id="mainwrap">
<header id="top"><span id="prog" class="muted"></span><span id="code" class="code"></span><span id="usr" class="muted"></span><span id="likes" class="muted"></span><span id="dur" class="muted"></span><span id="audio" class="muted"></span><a id="vlink" target="_blank" class="muted">open reel ↗</a></header>
<div id="meta"><div id="caption"></div><div id="reason"></div><div id="transcript" class="transcript"></div></div>
<div id="frames"></div>
</div>
<div id="help">Keys: <kbd>g</kbd> approve &middot; <kbd>w</kbd> reject &middot; <kbd>r</kbd> choose category (<kbd>1</kbd>-<kbd>12</kbd>) &middot; <kbd>u</kbd> undo &middot; <kbd>&larr;</kbd>/<kbd>&rarr;</kbd> focus frame &middot; <kbd>p</kbd>/<kbd>n</kbd> prev/next video &middot; <kbd>s</kbd> submit</div>
<div id="modal" class="hidden"><div id="modalbox"><h3>Choose a category</h3><div class="cats" id="cats"></div></div></div>
<script>
const CATS=['comedy','animals','food','sports_fitness','travel_nature','everyday_life','art_diy','science_technology','beauty_fashion','music_dance','gaming','other'];
let CUR=null,SEL=0,ORDER=[],DONE={},DRAFT=new Set(),TEAM=false;
const $=id=>document.getElementById(id);
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});return r.json();}
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function flagNames(m){const out=[];if(!m)return out;
 if(m.political!=='no')out.push('political?');
 if(m.sensitive!=='no')out.push('sensitive?');
 if(!(m.meaningful_text_language==='english'||m.meaningful_text_language==='none'))out.push('text lang?');
 if(m.us_audience_context!=='suitable')out.push('context?');
 if((m.confidence||0)<0.8)out.push('conf '+m.confidence);
 return out;}
function verdictLabel(v){if(v==='approve')return '✓ pass';if(v==='reject')return '✗ reject';return v||'';}
async function load(code){
 const d=await api('/api/item?code='+encodeURIComponent(code));
 CUR=d;SEL=0;
 const pos=ORDER.indexOf(code);
 $('prog').textContent='video '+(pos>=0?pos+1:0)+' / '+ORDER.length+' · ';
 $('code').textContent=code;
 $('usr').textContent='@'+(d.item.username||'?');
 $('likes').textContent=((d.item.likes==null?'?':d.item.likes)+' likes');
 $('dur').textContent=((d.item.duration_seconds==null?'?':d.item.duration_seconds)+'s');
 $('audio').textContent='audio: '+(d.item.audio_status||'?');
 $('vlink').href=d.item.url||'#';
 $('caption').textContent=d.item.caption||'(no caption)';
 $('reason').innerHTML='<b>model:</b> '+esc(d.item.status)+' / '+esc(d.item.reason)+' / category <b>'+esc(d.item.category)+'</b>';
 $('transcript').textContent=d.item.transcript?'transcript: '+d.item.transcript:'(no transcript)';
 const fr=$('frames');fr.innerHTML='';
 (d.item.frames||[]).forEach((fm,i)=>{
  const card=document.createElement('div');card.className='card'+(fm.flagged?' flagged':'');
  card.innerHTML='<img src="/frames/'+encodeURIComponent(code)+'/'+encodeURIComponent(fm.file)+'">'
   +'<div class="info">t='+fm.time+'s · model: '+(fm.model?esc(fm.model.category)+' '+fm.model.confidence:'-')+'</div>';
  const tags=flagNames(fm.model);
  if(tags.length){const t=document.createElement('div');t.className='info';
   tags.forEach(x=>{const s=document.createElement('span');s.className='tag';s.textContent=x;t.appendChild(s);});
   card.appendChild(t);}
  card.onclick=()=>{SEL=i;select();};
  fr.appendChild(card);});
 if(!(d.item.frames||[]).length){
  fr.innerHTML='<div class="info">No frame evidence captured yet — run review_capture.py, or open <a href="'+esc(d.item.url)+'" target="_blank">the reel</a> and decide from the video.</div>';}
 select();markCur();}
function select(){const cards=document.querySelectorAll('.card');cards.forEach((c,i)=>c.classList.toggle('sel',i===SEL));const c=cards[SEL];if(c)c.scrollIntoView({block:'nearest'});}
function markCur(){document.querySelectorAll('#side .se').forEach(el=>el.classList.toggle('cur',el.dataset.code===CUR.code));}
function seEntry(code,verdict){
 const d=document.createElement('div');d.className='se';d.dataset.code=code;
 d.innerHTML='<span class="c">'+esc(code)+'</span><span class="v '+(verdict==='approve'?'pass':verdict==='reject'?'rej':'')+'">'+esc(verdictLabel(verdict))+'</span>'
  +(DRAFT.has(code)?'<span class="dot" title="not submitted yet"></span>':'');
 d.onclick=()=>load(code);
 return d;}
function refreshList(){
 const pending=$('list-pending'),decided=$('list-decided');
 pending.innerHTML='';decided.innerHTML='';
 let np=0,nd=0;
 ORDER.forEach(code=>{
  const v=DONE[code]||'';
  const el=seEntry(code,v);
  if(v){decided.appendChild(el);nd++;}
  else{pending.appendChild(el);np++;}});
 $('n-pending').textContent=np;$('n-decided').textContent=nd;
 $('side-prog').textContent=(TEAM?('answered '+nd+' / '+ORDER.length):'');
 const sub=$('btn-submit');
 sub.disabled=!DRAFT.size;
 sub.textContent=DRAFT.size?('Submit '+DRAFT.size+(DRAFT.size===1?' decision':' decisions')):'All decisions submitted';
 markCur();}
async function decide(action,category){
 const r=await api('/api/decide',{code:CUR.code,action,category});
 await refreshList();
 if(r.next){load(r.next);}
 else if(TEAM){
  $('frames').innerHTML='<div class="done">All videos decided ✓<br><span style="font-size:14px;color:#5b6b80">Check your answers in the sidebar, go back and change any of them, then press <b>Submit</b> (<kbd>s</kbd>).</span></div>';
 }else document.body.innerHTML='<div class="done">Queue complete ✓</div>';}
function step(dir){
 if(!ORDER.length||!CUR)return;
 const i=ORDER.indexOf(CUR.code),j=Math.min(ORDER.length-1,Math.max(0,i+dir));
 if(j!==i)load(ORDER[j]);}
function openModal(){$('modal').classList.remove('hidden');const c=$('cats');c.innerHTML='';
 CATS.forEach((name,i)=>{const b=document.createElement('button');b.textContent=(i+1)+' '+name;
  b.onclick=()=>{closeModal();decide('category',name);};c.appendChild(b);});}
function closeModal(){$('modal').classList.add('hidden');}
async function submitAll(){
 const msg=$('side-submsg');
 if(!DRAFT.size){msg.textContent='Nothing new to submit.';return;}
 const r=await api('/api/submit');
 msg.textContent=r.error||r.message||'Done.';msg.style.color=r.error?'#b3261e':'#1a7f37';
 await refreshList();}
$('btn-submit').onclick=submitAll;
$('btn-prev').onclick=()=>step(-1);
$('btn-next').onclick=()=>step(1);
document.addEventListener('keydown',e=>{
 if(!$('modal').classList.contains('hidden')){
  if(e.key>='1'&&e.key<='9'&&Number(e.key)<=CATS.length){const n=Number(e.key);if(n>=1&&n<=CATS.length){closeModal();decide('category',CATS[n-1]);}}
  else if(e.key==='Escape')closeModal();
  return;}
 if(!CUR)return;
 if(e.key==='g')decide('approve');
 else if(e.key==='w')decide('reject');
 else if(e.key==='r')openModal();
 else if(e.key==='u'){api('/api/undo').then(async r=>{await refreshList();if(r.code)load(r.code);});}
 else if(e.key==='n')step(1);
 else if(e.key==='p')step(-1);
 else if(e.key==='s')submitAll();
 else if(e.key==='ArrowRight'&&CUR.item.frames.length){SEL=Math.min(SEL+1,CUR.item.frames.length-1);select();}
 else if(e.key==='ArrowLeft'){SEL=Math.max(SEL-1,0);select();}
});
api('/api/list').then(async q=>{
 if(q.team){
  TEAM=true;
  ORDER=q.items.map(i=>i.code);
  DONE={};q.items.forEach(i=>{if(i.verdict)DONE[i.code]=i.verdict==='category'?(i.category||'category'):i.verdict;});
  DRAFT=new Set(q.draft||[]);
  const t=document.createElement('span');t.className='muted';$('top').appendChild(t);
  t.textContent=q.team.user+' · answered '+Object.keys(DONE).length+'/'+ORDER.length;
  await refreshList();
  const pend=ORDER.filter(c=>!DONE[c]);
  if(pend.length)load(pend[0]);
  else{$('frames').innerHTML='<div class="done">All '+ORDER.length+' videos already decided ✓<br><span style="font-size:14px;color:#5b6b80">Jump to any video in the sidebar to change your decision, then press <b>Submit</b> (<kbd>s</kbd>).</span></div>';}
 }else{
  document.body.classList.add('no-side');
  const legacy=await api('/api/queue');
  ORDER=legacy.items.map(i=>i.code);
  if(ORDER.length)load(ORDER[0]);
  else document.body.innerHTML='<div class="done">No review items.<br>If the queue should not be empty, run: python review_capture.py</div>';}
});
</script></body></html>'''


def shortcode(url):
    return re.sub(r'.*/reels?/([\w-]+)/?', r'\1', url)


def queue():
    user = STATE.get('team_user')
    if user:
        # Team mode: the queue is the merged pool minus MY opinions.
        pool = rt.pool()
        done = rt.latest_opinions(user)
        urls = [u for u in pool if u not in done]
        urls.sort(key=lambda u: pool[u].get('first_seen_utc') or '')
        return [pool[u].get('code') or shortcode(u) for u in urls]
    db = sqlite3.connect(Path(STATE['store']) / 'feed_collection.sqlite')
    db.row_factory = sqlite3.Row
    rows = [dict(r) for r in db.execute(
        "SELECT url FROM feed_items WHERE status='review' ORDER BY first_seen_utc")]
    db.close()
    return [shortcode(r['url']) for r in rows]


def list_state():
    """Sidebar state: every video in pool order with my verdict (if any),
    plus which of my decisions are still unsent (drafts)."""
    user = STATE.get('team_user')
    if not user:
        return {'team': False, 'items': []}
    pool = rt.pool()
    latest = rt.latest_opinions(user)
    order = sorted(pool, key=lambda u: pool[u].get('first_seen_utc') or '')
    items = []
    for u in order:
        op = latest.get(u)
        items.append({'code': pool[u].get('code') or shortcode(u),
                      'verdict': op.get('action') if op else None,
                      'category': (op.get('category') if op else '') or ''})
    return {'team': {'user': user}, 'items': items,
            'draft': sorted(STATE['draft'])}


def submit():
    """Upload all decisions (drafts and any earlier unsent ones) at once."""
    user = STATE.get('team_user')
    if not user:
        raise RuntimeError('team mode only')
    count = len(STATE['draft'])
    rt.sync_push('review', quiet=True)
    STATE['draft'].clear()
    return {'count': count,
            'message': (f'Submitted {count} decision(s) — synced to the shared repo.'
                        if count else 'Everything was already submitted.')}


def item_data(code):
    path = Path(STATE['frames']) / code / 'meta.json'
    if path.exists():
        item = json.loads(path.read_text(encoding='utf-8'))
    elif STATE.get('team_user'):
        # No local frame evidence: build the card from the team pool metadata.
        entry = rt.pool().get(f'https://www.instagram.com/reel/{code}/') or {}
        item = {'url': f'https://www.instagram.com/reel/{code}/',
                'username': entry.get('username') or '',
                'caption': entry.get('caption') or '',
                'likes': entry.get('likes'),
                'status': entry.get('model_status') or 'review',
                'reason': entry.get('model_reason') or 'no_frame_evidence',
                'category': entry.get('model_category') or 'other',
                'audio_status': entry.get('audio_status'),
                'transcript': '', 'duration_seconds': entry.get('duration_seconds'),
                'frames': []}
    else:
        item = {'url': f'https://www.instagram.com/reel/{code}/', 'username': '',
                'caption': '', 'likes': None, 'status': 'review',
                'reason': 'no_frame_evidence', 'category': 'other',
                'audio_status': None, 'transcript': '', 'duration_seconds': None,
                'frames': []}
    items = queue()
    return {'code': code, 'item': item,
            'index': items.index(code) if code in items else 0, 'total': len(items)}


def refresh_reports():
    s = f.Store(STATE['store'])
    s.export()
    s.db.close()


def apply(code, action, category):
    user = STATE.get('team_user')
    url = f'https://www.instagram.com/reel/{code}/'
    old = None
    db = sqlite3.connect(Path(STATE['store']) / 'feed_collection.sqlite')
    db.row_factory = sqlite3.Row
    row = db.execute('SELECT status, reason, category FROM feed_items WHERE url=?',
                     (url,)).fetchone()
    if row is not None:
        old = (row['status'], row['reason'], row['category'])
        if action == 'reject':
            new = ('excluded', f'human_excluded_after_review (model: {old[1]})', old[2])
        elif action == 'category':
            new = ('screened_candidate',
                   f'human_approved_with_category (model: {old[1]})', category or old[2])
        else:
            new = ('screened_candidate', f'human_approved_after_review (model: {old[1]})',
                   old[2])
        db.execute('UPDATE feed_items SET status=?, reason=?, category=? WHERE url=?',
                   (*new, url))
        db.commit()
    db.close()
    if user:
        # Team mode: decisions are drafts until Submit. Appending a new line
        # for the same video changes the earlier decision (latest wins).
        op = rt.record_opinion(user, url, action, category or '')
        STATE['undo'].append((code, old, op['id']))
        STATE['draft'].add(code)
        if old is not None:
            refresh_reports()
        return True
    if old is None:
        return False
    STATE['undo'].append((code, old))
    refresh_reports()
    return True


def undo():
    if not STATE['undo']:
        return None
    entry = STATE['undo'].pop()
    code, old = entry[0], entry[1]
    user = STATE.get('team_user')
    if user and len(entry) == 3:
        rt.remove_opinion(user, entry[2])
        url = f'https://www.instagram.com/reel/{code}/'
        if url not in rt.latest_opinions(user):
            STATE['draft'].discard(code)
    if old is not None:
        db = sqlite3.connect(Path(STATE['store']) / 'feed_collection.sqlite')
        db.execute('UPDATE feed_items SET status=?, reason=?, category=? WHERE url=?',
                   (*old, f'https://www.instagram.com/reel/{code}/'))
        db.commit()
        db.close()
        refresh_reports()
    return code


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body, ctype):
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/':
            self.send_bytes(PAGE.encode(), 'text/html; charset=utf-8')
            return
        if path == '/api/list':
            self.send_json(list_state())
            return
        if path == '/api/queue':
            resp = {'items': [{'code': c} for c in queue()]}
            user = STATE.get('team_user')
            if user:
                resp['team'] = {'user': user,
                                'done': len(rt.latest_opinions(user)),
                                'pool': len(rt.pool())}
            self.send_json(resp)
            return
        if path == '/api/item':
            code = parse_qs(urlparse(self.path).query).get('code', [''])[0]
            self.send_json(item_data(code))
            return
        if path.startswith('/frames/'):
            root = Path(STATE['frames']).resolve()
            target = (root / path[len('/frames/'):]).resolve()
            if not str(target).startswith(str(root) + '/') or not target.is_file():
                self.send_error(404)
                return
            self.send_bytes(target.read_bytes(), 'image/jpeg')
            return
        self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        data = json.loads(self.rfile.read(length) or b'{}')
        try:
            if self.path == '/api/decide':
                apply(data.get('code'), data.get('action'), data.get('category'))
                rest = queue()
                self.send_json({'next': rest[0] if rest else None})
                return
            if self.path == '/api/undo':
                self.send_json({'code': undo()})
                return
            if self.path == '/api/submit':
                result = submit()
                self.send_json({'ok': True, **result})
                return
        except (ValueError, RuntimeError) as exc:
            self.send_json({'error': str(exc)})
            return
        self.send_error(404)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--store', default='feed_candidates_mine', help='collection folder')
    ap.add_argument('--frames', default='review_frames', help='evidence folder from review_capture.py')
    ap.add_argument('--port', type=int, default=8765, help='local server port')
    ap.add_argument('--no-browser', action='store_true', help='do not open the browser')
    args = ap.parse_args()
    STATE['store'] = args.store
    STATE['frames'] = args.frames
    STATE['team_user'] = rt.session_user() if rt.SYNC.is_dir() else None
    if STATE['team_user']:
        try:
            rt.sync_pull(quiet=True)
        except Exception as exc:
            print(f'Team pull failed ({type(exc).__name__}: {exc}) -- continuing with local state.')
        else:
            print(f"Team mode: logged in as {STATE['team_user']} -- "
                  f'{len(rt.pool())} videos in the pool, {len(queue())} left for you.')

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Review queue: http://127.0.0.1:{args.port}   (store={args.store})')
    print(f'Review items queued: {len(queue())}')
    print('Keys: g approve · w reject · r category · u undo · p/n prev/next video · s submit')
    print('Decisions stay local until you press s (Submit) — then they all go up at once.')
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, [f'http://127.0.0.1:{args.port}']).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()
