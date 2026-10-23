"""楠團德州扑克 — private, six-member, LAN poker ledger. Python 3.10+."""
from __future__ import annotations

import argparse
import csv
from contextlib import contextmanager
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import sqlite3
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import online
import wallet
import clubhouse
import social
import voice_transport
import club_admin
import game_settings
import transfers
import member_accounts
from realtime import Hub, WriteQueue
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit
from poker_engine import RuleError

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("POKER_DB", ROOT / "data" / "poker.sqlite3"))
AUTH_LOCK = threading.Lock()
ATTEMPTS: dict[str, list[float]] = {}
CLIENT_EVENT_AT = {}
CLIENT_EVENT_BUDGET = {}
SESSION_SECONDS = 7 * 24 * 3600
SECURE_COOKIE = os.environ.get("POKER_SECURE_COOKIE", "0") == "1"
PUBLIC_ORIGIN = os.environ.get("POKER_PUBLIC_ORIGIN", "").rstrip("/")
REQUIRE_INVITE = os.environ.get("POKER_REQUIRE_INVITE", "0") == "1"
EVENTS = Hub()
WRITES = WriteQueue()
SNAPSHOTS = threading.Semaphore(1)
LOBBY_SNAPSHOTS = threading.Semaphore(1)
# Interactive replies must not queue behind every SSE viewer.
HTTP_SNAPSHOTS = threading.Semaphore(2)


@dataclass
class Reply:
    status: int
    value: dict
    cookie: str | None = None
    snapshot_room_id: int | None = None


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE NOT NULL,
            nickname TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, played_on TEXT NOT NULL,
            unit TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
            creator_id INTEGER NOT NULL REFERENCES users(id),
            status TEXT NOT NULL CHECK(status IN ('active','settled','cancelled')),
            revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, settled_at TEXT);
        CREATE TABLE IF NOT EXISTS entries (
            game_id INTEGER NOT NULL REFERENCES games(id), user_id INTEGER NOT NULL REFERENCES users(id),
            buy_in INTEGER NOT NULL CHECK(buy_in>=0), cash_out INTEGER CHECK(cash_out>=0),
            PRIMARY KEY(game_id,user_id));
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY, game_id INTEGER REFERENCES games(id),
            user_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL,
            details TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        db.execute("INSERT OR IGNORE INTO settings VALUES ('invite_code',?)", (secrets.token_hex(4).upper(),))
        online.initialize(db)
        transfers.initialize(db)


class Problem(Exception):
    def __init__(self, message, status=400, reason=None):
        self.message, self.status, self.reason = message, status, reason


def clean(value, label, maximum=60):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise Problem(f"{label}需填写 1–{maximum} 个字。")
    return value.strip()


def money(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)) or str(value).strip() == "":
        raise Problem("请填写有效的金额。")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > 100_000_000 or amount.as_tuple().exponent < -2:
            raise Problem("金额须介于 0 和 100,000,000 之间，最多两位小数。")
        return int(amount * 100)
    except InvalidOperation:
        raise Problem("请填写有效的金额。")


def pass_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()


def audit(db, game_id, user_id, action, details):
    db.execute("INSERT INTO audit(game_id,user_id,action,details,created_at) VALUES(?,?,?,?,?)",
               (game_id, user_id, action, json.dumps(details, ensure_ascii=False), now()))


def snapshot(db):
    users = [dict(r) for r in db.execute("SELECT id,username,nickname,created_at FROM users ORDER BY id")]
    games = [dict(r) for r in db.execute("SELECT * FROM games WHERE status!='cancelled' ORDER BY played_on DESC,id DESC")]
    for game in games:
        game["entries"] = [dict(r) for r in db.execute(
            "SELECT user_id,buy_in,cash_out FROM entries WHERE game_id=? ORDER BY user_id", (game["id"],))]
    return {"users": users, "games": games,
            "invite_code": db.execute("SELECT value FROM settings WHERE key='invite_code'").fetchone()[0]}


class GameHTTPServer(ThreadingHTTPServer):
    # Forty SSE clients plus a simultaneous heartbeat/reconnect burst must not
    # overflow the stdlib default backlog of five before a handler is started.
    request_queue_size = 128


class Handler(BaseHTTPRequestHandler):
    server_version = "PokerClub/1.0"
    disable_nagle_algorithm = True
    timeout = 10  # Bound abandoned headers/bodies; SSE sets its own write timeout.

    def log_message(self, fmt, *args):
        # Never log request bodies, passwords, or cookies.
        print(f"[{now()}] {self.address_string()} {fmt % args}", flush=True)

    def reply(self, status, value, cookie=None, content_type="application/json; charset=utf-8", attachment=None):
        if hasattr(self,'request_id') and isinstance(value,dict):
            value={**value,'request_id':self.request_id}
        encoded_at=time.monotonic()
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        if hasattr(self,'timings'):
            self.timings['encode']=(time.monotonic()-encoded_at)*1000
            self.timings['server']=(time.monotonic()-self.started)*1000
        if hasattr(self,"request_id"):
            if isinstance(value,dict):
                value = {**value,"request_id":self.request_id}
            metrics = {k:round(v,2) for k,v in self.timings.items()}
            metrics["total"] = round((time.monotonic()-self.started)*1000,2)
            print(json.dumps({"event":"request_done","request_id":self.request_id,"path":self.path.split("?",1)[0],"status":status,"reason":value.get("reason") if isinstance(value,dict) else None,"ms":metrics}),flush=True)
        self.send_response(status)
        if hasattr(self,"request_id"):
            self.send_header("X-Request-ID",self.request_id)
            self.send_header("Server-Timing",", ".join(f"{k};dur={v:.2f}" for k,v in self.timings.items()))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        # Safari does not consistently map connect-src self to the WSS scheme.
        socket_sources=''
        host=self.headers.get('Host','')
        if re.fullmatch(r'[A-Za-z0-9.\-]+(?::[0-9]{1,5})?',host):socket_sources=' ws://'+host+' wss://'+host
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'"+socket_sources+"; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        self.end_headers()
        self.wfile.write(body)

    def user(self, db):
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
            token = jar["poker_session"].value
        except Exception:
            raise Problem("请先登录。", 401)
        row = db.execute("SELECT u.* FROM users u JOIN auth_sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires>?",
                         (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        if not row:
            raise Problem("登录已过期，请重新登录。", 401)
        member_accounts.require_active(db,row['id'])
        return row

    def login_session(self, db, user_id):
        token = secrets.token_urlsafe(40)
        db.execute("DELETE FROM auth_sessions WHERE expires<=?", (time.time(),))
        db.execute("INSERT INTO auth_sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user_id, time.time()+SESSION_SECONDS))
        return f"poker_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}" + ("; Secure" if SECURE_COOKIE else "")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/online/events":
                return self.event_stream()
            elif path == '/api/social/voice/socket':
                query=parse_qs(urlsplit(self.path).query)
                rid=int(query.get('room',['0'])[0]);session=query.get('session',[''])[0]
                origin=self.headers.get('Origin','');host=self.headers.get('Host','')
                allowed={v for v in (PUBLIC_ORIGIN,'https://'+host,'http://'+host) if v}
                if not origin or origin not in allowed:raise Problem('語音連線來源無效。',403)
                with connect() as db:
                    db.execute('PRAGMA query_only=ON');db.execute('BEGIN');user=self.user(db);uid=user['id']
                    if not social.voice_member(db,rid,uid,session,time.time()):raise Problem('請先加入語音。',403)
                def authorize_voice():
                    try:
                        with connect() as db:
                            db.execute('PRAGMA query_only=ON');db.execute('BEGIN');current=self.user(db)
                            return current['id']==uid and social.voice_member(db,rid,uid,session,time.time())
                    except Exception:return False
                return voice_transport.serve(self,uid,rid,session,authorize_voice)
            elif path == '/api/social/voice/state':
                query=parse_qs(urlsplit(self.path).query)
                with connect() as db:
                    db.execute('PRAGMA query_only=ON');db.execute('BEGIN');user=self.user(db)
                    value=social.voice_state(db,int(query.get('room',['0'])[0]),user['id'],time.time())
                self.reply(200,value)
            elif path == "/api/bootstrap":
                with connect() as db:
                    count = db.execute("SELECT count(*) FROM users").fetchone()[0]
                    self.reply(200, {"member_count": count, "capacity": 6,"table_capacity":6,"account_limit":None, "requires_invite": REQUIRE_INVITE or count > 0})
            elif path == '/api/admin/accounts':
                query=parse_qs(urlsplit(self.path).query)
                with connect() as db:
                    user=self.user(db)
                    db.execute('BEGIN')
                    value=club_admin.accounts(db,user,time.time(),query.get('search',[''])[0],query.get('page',['1'])[0])
                self.reply(200,value)
            elif (member_match:=re.fullmatch(r'/api/members/(\d{1,10})',path)):
                query=parse_qs(urlsplit(self.path).query)
                with HTTP_SNAPSHOTS, connect() as db:
                    db.execute('PRAGMA query_only=ON');db.execute('BEGIN');self.user(db)
                    value=clubhouse.public_profile(db,int(member_match[1]),time.time(),query.get('period',['7d'])[0])
                self.reply(200,value)
            elif path=='/api/admin/game-settings':
                with connect() as db:
                    db.execute('PRAGMA query_only=ON');db.execute('BEGIN');user=self.user(db)
                    value=game_settings.admin_view(db,user)
                self.reply(200,value)
            elif path=='/api/clubhouse/staff':
                with HTTP_SNAPSHOTS, connect() as db:
                    db.execute('PRAGMA query_only=ON');db.execute('BEGIN');user=self.user(db)
                    value=clubhouse.staff_view(db,user['id'],time.time())
                self.reply(200,value)
            elif path=='/api/profile':
                with connect() as db:
                    user=self.user(db);self.reply(200,{'profile':member_accounts.profile(db,user['id'])})
            elif (image_match:=re.fullmatch(r'/api/profile/avatar/(\d+)/(\d+)\.png',path)):
                with connect() as db:
                    self.user(db)
                    picture=db.execute('SELECT avatar_png FROM member_profiles WHERE user_id=? AND revision=?',tuple(map(int,image_match.groups()))).fetchone()
                    if not picture or not picture[0]:raise Problem('找不到頭像。',404)
                    self.reply(200,picture[0],content_type='image/png')
            elif path in ('/api/wallet/transfers','/api/wallet/recipients'):
                query=parse_qs(urlsplit(self.path).query)
                with connect() as db:
                    user=self.user(db);db.execute('BEGIN')
                    value=transfers.history(db,user['id'],time.time(),query.get('before',[None])[0]) if path.endswith('/transfers') else transfers.recipients(db,user['id'],query.get('search',[''])[0])
                self.reply(200,value)
            elif path=='/api/online/diagnostics':
                with connect() as db:
                    self.user(db)
                self.reply(200,{'server_time':time.time(),'ok':True})
            elif (replay_match:=re.fullmatch(r'/api/online/rooms/(\d+)/replay/(\d+)',path)):
                with connect() as db:
                    user=self.user(db);db.execute('BEGIN')
                    value=online.club_features.replay(db,online.get_room(db,int(replay_match[1])),int(replay_match[2]),user['id'])
                self.reply(200,value)
            elif path == "/api/online/lobby" or re.fullmatch(r"/api/online/rooms/\d+", path):
                with WRITES.enter() as admission:
                    with connect() as db:
                        user = self.user(db)
                        db.execute("BEGIN IMMEDIATE")
                        clock = time.time()
                        requested_room = None if path.endswith('lobby') else int(path.rsplit('/',1)[1])
                        if requested_room:online.club_features.require_access(online.get_room(db,requested_room),user['id'])
                        online.presence(db,user['id'],requested_room,clock)
                        changed = online.maintenance(db, clock, due_at=admission.received_at)
                        db.commit()
                if changed:
                    EVENTS.publish()
                # Maintenance stays FIFO; expensive private snapshots use a WAL
                # read transaction after releasing the shared action queue.
                with HTTP_SNAPSHOTS, connect() as reader:
                    reader.execute('PRAGMA query_only=ON');reader.execute('BEGIN')
                    user = self.user(reader)
                    value = online.lobby(reader,user,clock,touch_presence=False) if requested_room is None else online.room_view(reader,requested_room,user['id'],clock,touch_presence=False)
                self.reply(200, value)
            elif path in ("/api/state", "/api/export"):
                with connect() as db:
                    user = self.user(db)
                    db.execute("BEGIN")
                    state = snapshot(db)
                    state["me"] = {k: user[k] for k in ("id", "username", "nickname")}
                    if path == "/api/state":
                        self.reply(200, state)
                    else:
                        out = io.StringIO(newline="")
                        writer = csv.writer(out)
                        writer.writerow(["日期", "牌局", "单位", "玩家", "买入", "带出", "净输赢"])
                        people = {u["id"]: u for u in state["users"]}
                        # Text cells are protected from spreadsheet formula injection.
                        def cell(s):
                            return "'" + s if s.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else s
                        for g in state["games"]:
                            if g["status"] == "settled":
                                for e in g["entries"]:
                                    writer.writerow([g["played_on"], cell(g["title"]), cell(g["unit"]),
                                        cell(people[e["user_id"]]["nickname"]), f'{e["buy_in"]/100:.2f}',
                                        f'{e["cash_out"]/100:.2f}', f'{(e["cash_out"]-e["buy_in"])/100:.2f}'])
                        self.reply(200, out.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8", attachment="poker-records.csv")
            elif path=='/assets/poker-night.webp' or re.fullmatch(r'/assets/clubhouse/tier-[1-4](?:-small)?\.webp',path) or re.fullmatch(r'/assets/covers/(?:holdem|big2|blackjack|roulette|baccarat|slot|mines|dice|tower|inbetween|mahjong)\.webp',path):
                self.reply(200,(ROOT/'static'/path[1:]).read_bytes(),content_type='image/webp')
            elif path in ("/mahjong.js", "/mahjong.css", "/game-settings.js", "/game-settings.css", "/", "/index.html", "/app.js", "/style.css", "/game.js", "/profile.js", "/clubhouse-scene.js", "/clubhouse-scene.css", "/night.css", "/profile.css", "/effects.css", "/features.js", "/features.css", "/transfers.js", "/transfers.css", "/casino.css", "/ui.css", "/arcade-motion.js", "/bonus.js", "/club.js", "/arcade.js", "/arcade.css", "/voice-worklet.js", "/social.js", "/admin.js", "/dealer.js", "/favicon.svg", "/ledger", "/ledger.html", "/ledger.js", "/ledger.css"):
                name = "index.html" if path == "/" else "ledger.html" if path == "/ledger" else path[1:]
                types = {"html": "text/html", "js": "text/javascript", "css": "text/css", "svg": "image/svg+xml"}
                self.reply(200, (ROOT / "static" / name).read_bytes(), content_type=types[name.rsplit(".",1)[-1]]+"; charset=utf-8")
            else:
                raise Problem("页面不存在。", 404)
        except (club_admin.AdminError,transfers.TransferError,member_accounts.AccountError) as ex:
            self.reply(ex.status,{'error':ex.message,'reason':ex.reason})
        except RuleError as ex:
            self.reply(400, {"error": str(ex)})
        except Problem as ex:
            self.reply(ex.status, {"error": ex.message})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as ex:
            print(type(ex).__name__, str(ex), flush=True)
            self.reply(500, {"error": "读取失败，请稍后重试。"})

    def event_stream(self):
        query = parse_qs(urlsplit(self.path).query)
        raw_room = query.get("room", [""])[0]
        if raw_room and not re.fullmatch(r"[1-9]\d{0,9}", raw_room):
            raise Problem("牌桌編號無效。")
        room_id = int(raw_room) if raw_room else None
        client_presence = query.get('presence',[''])[0] == 'client'
        client_id = query.get('client',[''])[0] or None
        if client_id is not None and not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',client_id):
            raise Problem('即時連線識別碼無效。')
        # Validate before sending streaming headers; never leave a DB transaction
        # or connection open while waiting for events or a slow network client.
        with connect() as db:
            uid = self.user(db)["id"]
            if room_id:
                online.club_features.require_access(online.get_room(db, room_id),uid)
        try:
            subscription = EVENTS.subscribe(uid,client_id)
            lease = subscription.__enter__()
        except ValueError as error:
            raise Problem(str(error), 429)
        stream_id=secrets.token_hex(8);started=time.monotonic();states=pings=0;reason='closed'
        agent=self.headers.get('User-Agent','')
        meta={'stream_id':stream_id,'client':client_id,'user_id':uid,'room_id':room_id,'mobile':'Mobile' in agent,'browser':'Edge' if 'Edg/' in agent else 'Chrome' if 'Chrome/' in agent else 'Firefox' if 'Firefox/' in agent else 'Safari' if 'Safari/' in agent else 'other'}
        print(json.dumps({'event':'stream_open',**meta,'at':now()}),flush=True)
        try:
            self.connection.settimeout(15)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, no-transform")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(b"retry: 1000\n\n")
            self.wfile.flush()
            first_snapshot = True
            sent_version = None
            last_snapshot = 0
            while not EVENTS.stopped and not lease.is_set():
                version = EVENTS.version_for(room_id)
                try:
                    # Only the tiny presence write joins the action queue. Snapshot
                    # construction uses a consistent WAL read transaction, never a
                    # write reservation that could hold up another player's move.
                    if not client_presence or first_snapshot:
                        with WRITES.enter():
                            with connect() as db:
                                self.user(db);online.presence(db,uid,room_id,time.time());db.commit()
                    if version!=sent_version or time.monotonic()-last_snapshot>=15:
                        # Coalesce bursty lobby updates and bound CPU-heavy readers
                        # independently from FIFO game writes. Recheck the channel
                        # before BEGIN so a queued snapshot cannot mark stale data
                        # as the latest published version.
                        gap=(.02 if room_id else .5)-(time.monotonic()-last_snapshot)
                        if gap>0:lease.wait(gap)
                        with (SNAPSHOTS if room_id else LOBBY_SNAPSHOTS):
                            version=EVENTS.version_for(room_id)
                            with connect() as db:
                                db.execute('PRAGMA query_only=ON');db.execute('BEGIN');user=self.user(db);clock=time.time()
                                value=online.room_view(db,room_id,uid,clock,touch_presence=False) if room_id else online.lobby(db,user,clock,touch_presence=False)
                    else:
                        with connect() as db:
                            db.execute('BEGIN');self.user(db);clock=time.time();value=None
                    first_snapshot = False
                except Problem as error:
                    reason='auth'
                    self.wfile.write(b"event: auth\ndata: {}\n\n")
                    self.wfile.flush()
                    return
                if lease.is_set():
                    reason='replaced'
                    break
                if value is None:
                    payload=json.dumps({'server_time':clock}).encode()
                    self.wfile.write(b'event: ping\ndata: '+payload+b'\n\n');pings+=1
                else:
                    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
                    self.wfile.write(b"event: state\ndata: " + payload + b"\n\n");states+=1
                    sent_version=version
                    last_snapshot=time.monotonic()
                self.wfile.flush()
                EVENTS.wait(version,timeout=3,room_id=room_id,cancelled=lease)
            if EVENTS.stopped:reason='server_stop'
            elif lease.is_set():reason='replaced'
        except (OSError, ConnectionError) as error:
            reason=type(error).__name__
        except Exception as error:
            reason=type(error).__name__
            print(json.dumps({'event':'stream_error',**meta,'error':reason,'at':now()}),flush=True)
        finally:
            subscription.__exit__(None, None, None)
            self.close_connection = True
            print(json.dumps({'event':'stream_close',**meta,'reason':reason,'states':states,'pings':pings,'duration_s':round(time.monotonic()-started,3),'at':now()}),flush=True)

    def do_POST(self):
        self.request_id = secrets.token_hex(8)
        self.started = time.monotonic()
        self.timings = {}
        print(json.dumps({"event":"request_start","request_id":self.request_id,"path":self.path.split("?",1)[0],"at":now()}),flush=True)
        try:
            if self.headers.get("X-Requested-With") != "PokerClub" or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise Problem("无效的请求来源。", 403)
            origin = self.headers.get("Origin")
            allowed_origins = {f'http://{self.headers.get("Host")}', f'https://{self.headers.get("Host")}'}
            if PUBLIC_ORIGIN:
                allowed_origins.add(PUBLIC_ORIGIN)
            if origin and origin not in allowed_origins:
                raise Problem("请从本网站操作。", 403)
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > (110000 if self.path=='/api/profile' else 32768):
                raise Problem("请求内容无效。")
            try:
                data = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeDecodeError):
                raise Problem("请求格式无效。")
            if not isinstance(data, dict):
                raise Problem("请求格式无效。")
            self.timings["receive"] = (time.monotonic()-self.started)*1000
            self.auth_prepared=None
            if self.path in ('/api/register','/api/login'):
                started=time.monotonic()
                self.prepare_auth(data)
                self.timings['auth']=(time.monotonic()-started)*1000
            if self.path=='/api/profile/password':
                self.prepare_profile_password(data)
            with WRITES.enter() as admission:
                self.received_at = admission.received_at
                self.timings["queue"] = admission.queue_ms
                with connect() as db:
                    started = time.monotonic()
                    db.execute("BEGIN IMMEDIATE")
                    self.timings["db_wait"] = (time.monotonic()-started)*1000
                    started = time.monotonic()
                    response = self.mutate(db, data)
                    self.timings["process"] = max(0,(time.monotonic()-started)*1000-self.timings.get('commit',0))
            if response.snapshot_room_id is not None:
                started=time.monotonic()
                with HTTP_SNAPSHOTS, connect() as reader:
                    reader.execute('PRAGMA query_only=ON');reader.execute('BEGIN')
                    user=self.user(reader)
                    state=online.room_view(reader,response.snapshot_room_id,user['id'],time.time(),touch_presence=False)
                self.timings['snapshot']=(time.monotonic()-started)*1000
                response.value['state']=state
            self.reply(response.status,response.value,cookie=response.cookie)
        except (club_admin.AdminError,transfers.TransferError,member_accounts.AccountError) as ex:
            self.reply(ex.status,{'error':ex.message,'reason':ex.reason})
        except RuleError as ex:
            self.reply(400, {"error": str(ex),"reason":"invalid_action"})
        except Problem as ex:
            self.reply(ex.status, {"error": ex.message,"reason":ex.reason or "invalid_request"})
        except (ValueError, TypeError, OverflowError):
            self.reply(400, {"error": "输入格式无效，请检查后重试。"})
        except TimeoutError:
            try:self.reply(408,{'error':'請求傳送逾時，請用相同操作確認結果。','reason':'request_timeout'})
            except OSError:self.close_connection=True
        except (BrokenPipeError, ConnectionResetError):
            pass
        except sqlite3.OperationalError as ex:
            print(type(ex).__name__, str(ex), flush=True)
            self.reply(503, {"error":"伺服器暫時忙碌，請用相同操作確認結果。","reason":"server_busy"})
        except Exception as ex:
            print(type(ex).__name__, str(ex), flush=True)
            self.reply(500, {"error": "保存失败，请稍后重试。"})

    def prepare_auth(self,data):
        """Do expensive password work outside the game transaction queue.

        Recheck registration constraints or the exact credential version under
        the write lock before inserting an account or issuing a session.
        """
        username=clean(data.get('username'),'账号',24);password=data.get('password')
        if not isinstance(password,str) or not 8<=len(password)<=128:raise Problem('密码需为 8–128 个字元。')
        ip=self.client_address[0];self.auth_attempt_key=f'user:{ip}:{username.casefold()}'
        with AUTH_LOCK:
            clock=time.time()
            for key,limit in ((self.auth_attempt_key,12),(f'ip:{ip}',120)):
                attempts=[t for t in ATTEMPTS.get(key,[]) if t>clock-600]
                ATTEMPTS[key]=attempts
                if len(attempts)>=limit:raise Problem('尝试次数太多，请 10 分钟后再试。',429)
            ATTEMPTS[self.auth_attempt_key].append(clock);ATTEMPTS[f'ip:{ip}'].append(clock)
            # Discard expired buckets instead of retaining arbitrary usernames forever.
            for key in list(ATTEMPTS):
                if not ATTEMPTS[key] or ATTEMPTS[key][-1]<=clock-600:del ATTEMPTS[key]
        with connect() as db:
            if self.path=='/api/register':
                if not re.fullmatch(r'[A-Za-z0-9_]{3,24}',username):raise Problem('账号请使用 3–24 位英文字母、数字或底线。')
                count=db.execute('SELECT count(*) FROM users').fetchone()[0]
                code=db.execute("SELECT value FROM settings WHERE key='invite_code'").fetchone()[0]
                if (count or REQUIRE_INVITE) and not hmac.compare_digest(str(data.get('invite_code','')).strip().upper(),code):raise Problem('邀请码不正确，请向已加入的室友索取。',403)
                clean(data.get('nickname'),'昵称',16)
                if db.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone():raise Problem('这个账号已被使用。',409)
                salt=secrets.token_hex(16)
            else:
                candidate=db.execute('SELECT id,salt,password_hash FROM users WHERE username=?',(username,)).fetchone()
                candidate=dict(candidate) if candidate else None
                salt=candidate['salt'] if candidate else '00'*16
        digest=pass_hash(password,salt)
        if self.path=='/api/login' and (not candidate or not hmac.compare_digest(digest,candidate['password_hash'])):raise Problem('账号或密码不正确。',401)
        self.auth_prepared={'salt':salt,'digest':digest,'user_id':candidate['id'] if self.path=='/api/login' else None}

    def prepare_profile_password(self,data):
        """Password derivation stays outside the shared game write queue."""
        current,new=data.get('current_password'),data.get('new_password')
        with connect() as db:
            user=dict(self.user(db));admin=club_admin.identity(db,user['id'])['is_admin']
        minimum=12 if admin else 8
        if not isinstance(current,str) or not 8<=len(current)<=128:raise Problem('請填寫目前密碼。')
        if not isinstance(new,str) or not minimum<=len(new)<=128 or current==new:raise Problem(f'新密碼需為 {minimum}–128 個字元，且與目前密碼不同。')
        key=f'password:{user["id"]}'
        with AUTH_LOCK:
            clock=time.time();attempts=[t for t in ATTEMPTS.get(key,[]) if t>clock-600]
            if len(attempts)>=12:raise Problem('嘗試次數過多，請 10 分鐘後重試。',429)
            ATTEMPTS[key]=attempts+[clock]
        if not hmac.compare_digest(pass_hash(current,user['salt']),user['password_hash']):raise Problem('目前密碼不正確。',403)
        salt=secrets.token_hex(16)
        self.profile_password={'previous_salt':user['salt'],'previous_hash':user['password_hash'],'salt':salt,'digest':pass_hash(new,salt)}

    def mutate(self, db, data):
        path = self.path
        if path in ("/api/register", "/api/login"):
            username = clean(data.get("username"), "账号", 24)
            password = data.get("password")
            if not isinstance(password, str) or len(password) < 8 or len(password) > 128:
                raise Problem("密码需为 8–128 个字元。")
            if path == "/api/register":
                if not re.fullmatch(r"[A-Za-z0-9_]{3,24}", username):
                    raise Problem("账号请使用 3–24 位英文字母、数字或底线。")
                count = db.execute("SELECT count(*) FROM users").fetchone()[0]
                code = db.execute("SELECT value FROM settings WHERE key='invite_code'").fetchone()[0]
                if (count or REQUIRE_INVITE) and not hmac.compare_digest(str(data.get("invite_code", "")).strip().upper(), code):
                    raise Problem("邀请码不正确，请向已加入的室友索取。", 403)
                nickname = clean(data.get("nickname"), "昵称", 16)
                if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                    raise Problem("这个账号已被使用。", 409)
                salt = self.auth_prepared['salt']
                user_id = db.execute("INSERT INTO users(username,nickname,salt,password_hash,created_at) VALUES(?,?,?,?,?)",
                                     (username, nickname, salt, self.auth_prepared['digest'], now())).lastrowid
            else:
                user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
                prepared=self.auth_prepared
                if not user or user['id']!=prepared['user_id'] or user['salt']!=prepared['salt'] or not hmac.compare_digest(prepared['digest'],user['password_hash']):
                    raise Problem("账号或密码不正确。", 401)
                user_id = user["id"]
            member_accounts.require_active(db,user_id)
            wallet.create(db,user_id,time.time())
            cookie = self.login_session(db, user_id)
            db.commit()
            with AUTH_LOCK:
                ATTEMPTS.pop(self.auth_attempt_key, None)
            return Reply(200, {"ok": True}, cookie=cookie)
        user = self.user(db)
        if path in ('/api/admin/game-settings','/api/admin/game-settings/preview'):
            club_admin.require(db,user['id'])
            if path.endswith('/preview'):
                kind=data.get('game_type');params=game_settings.validate(kind,data.get('params'));db.commit()
                return Reply(200,{'game_type':kind,'params':params,'metrics':game_settings.metrics(kind,params)})
            result=game_settings.update(db,user,data,time.time());db.commit();EVENTS.publish()
            return Reply(200,result)
        if path=='/api/profile':
            result=member_accounts.update(db,user,data,time.time());db.commit();EVENTS.publish()
            return Reply(200,result)
        if path=='/api/profile/password':
            prepared=self.profile_password
            if user['salt']!=prepared['previous_salt'] or user['password_hash']!=prepared['previous_hash']:raise Problem('密碼已在其他分頁變更，請重新登入。',409)
            db.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?',(prepared['salt'],prepared['digest'],user['id']))
            db.execute('UPDATE club_admins SET password_change_required=0 WHERE user_id=?',(user['id'],))
            db.execute('DELETE FROM auth_sessions WHERE user_id=?',(user['id'],));cookie=self.login_session(db,user['id']);db.commit();EVENTS.publish()
            return Reply(200,{'ok':True},cookie=cookie)
        if path=='/api/admin/account-action':
            result=member_accounts.moderate(db,user,data,time.time());db.commit();EVENTS.publish()
            return Reply(200,result)
        if path=='/api/online/client-event':
            kind=data.get('kind');client=data.get('client')
            if kind not in ('stream_error','stream_stale','stream_recovered','state_error','recovery_started','recovery_synced','recovery_cancelled','heartbeat_probe','page_hidden','network_offline') or not isinstance(client,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',client):raise Problem('連線回報格式無效。')
            fields={key:data[key] for key in ('room_id','revision','last_event_age_ms','duration_ms') if type(data.get(key)) in (int,float) and 0<=data[key]<=10**12}
            if 'attempt_id' in data:
                attempt=data['attempt_id']
                if not isinstance(attempt,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',attempt):raise Problem('恢復連線編號無效。')
                fields['attempt_id']=attempt
            allowed={'reason':('channel','reconnect','state_error','stream_error','stream_stale','heartbeat_probe','offline','online','hidden','visible','freeze','resume','pagehide','pageshow','focus'),
                     'delivery':('push','snapshot','http','ping'),'visibility':('visible','hidden','prerender')}
            for key,values in allowed.items():
                if key in data:
                    if not isinstance(data[key],str) or data[key] not in values:raise Problem('連線回報欄位無效。')
                    fields[key]=data[key]
            if type(data.get('online')) is bool:fields['online']=data['online']
            clock=time.monotonic()
            with AUTH_LOCK:
                # Keep start/snapshot/push phases independent across browser pages.
                # A quick successful recovery must not be hidden by its own error.
                for key in [k for k,v in CLIENT_EVENT_AT.items() if clock-v>=60]:del CLIENT_EVENT_AT[key]
                for uid in [u for u,v in CLIENT_EVENT_BUDGET.items() if clock-v[-1]>=60]:del CLIENT_EVENT_BUDGET[uid]
                key=(user['id'],client,kind,fields.get('attempt_id'))
                previous=CLIENT_EVENT_AT.get(key)
                if previous is not None and clock-previous<1:
                    db.commit();return Reply(200,{'ok':True,'duplicate':True})
                budget=[at for at in CLIENT_EVENT_BUDGET.get(user['id'],[]) if clock-at<60]
                if len(budget)>=120:raise Problem('連線回報過於頻繁。',429)
                if len(CLIENT_EVENT_AT)>=8192:del CLIENT_EVENT_AT[min(CLIENT_EVENT_AT,key=CLIENT_EVENT_AT.get)]
                CLIENT_EVENT_BUDGET[user['id']]=[*budget,clock];CLIENT_EVENT_AT[key]=clock
            print(json.dumps({'event':'client_connection','kind':kind,'client':client,'user_id':user['id'],**fields,'at':now()}),flush=True)
            db.commit();return Reply(200,{'ok':True})
        if path=='/api/wallet/transfers':
            role=club_admin.identity(db,user['id'])
            if role['is_admin']:club_admin.require(db,user['id'])
            result=transfers.send(db,user,data,time.time())
            db.commit();EVENTS.publish()
            return Reply(200,result)
        if path=='/api/online/presence':
            result=online.heartbeat(db,user['id'],data.get('room_id'),time.time())
            db.commit()
            if result['resumed']:EVENTS.publish()
            return Reply(200,result)
        if path=='/api/admin/password':
            club_admin.require(db,user['id'],allow_password_change=True)
            current,new=data.get('current_password'),data.get('new_password')
            if not isinstance(current,str) or not 8<=len(current)<=128 or not hmac.compare_digest(pass_hash(current,user['salt']),user['password_hash']):
                raise Problem('目前密碼不正確。',403)
            if not isinstance(new,str) or not 12<=len(new)<=128 or current==new:
                raise Problem('新密碼需為 12–128 個字元，且須與目前密碼不同。')
            salt=secrets.token_hex(16)
            db.execute('UPDATE users SET salt=?,password_hash=? WHERE id=?',(salt,pass_hash(new,salt),user['id']))
            db.execute('UPDATE club_admins SET password_change_required=0 WHERE user_id=?',(user['id'],))
            db.execute('DELETE FROM auth_sessions WHERE user_id=?',(user['id'],))
            cookie=self.login_session(db,user['id']);db.commit();EVENTS.publish()
            return Reply(200,{'ok':True},cookie=cookie)
        if path=='/api/admin/grants':
            result=club_admin.grant(db,user,data,time.time())
            db.commit();EVENTS.publish()
            return Reply(200,result)
        if path=='/api/admin/adjustments':
            result=club_admin.adjust(db,user,data,time.time())
            db.commit();EVENTS.publish()
            return Reply(200,result)
        if path in ('/api/clubhouse/hire','/api/clubhouse/dispatch','/api/clubhouse/collect'):
            clock=time.time();result=clubhouse.staff_mutate(db,user,path.rsplit('/',1)[1],data,clock);db.commit()
            if not result['replayed']:EVENTS.publish()
            return Reply(200,{**result,'staff':clubhouse.staff_view(db,user['id'],clock),'wallet':wallet.view(db,user['id'],clock),'server_time':clock})
        if path=='/api/wallet/clubhouse-upgrade':
            clock=time.time();result=clubhouse.upgrade(db,user,data,clock);db.commit()
            if not result['replayed']:EVENTS.publish()
            return Reply(200,{**result,'wallet':wallet.view(db,user['id'],clock),'server_time':clock})
        if path=='/api/wallet/passive':
            clock=time.time();result=clubhouse.claim(db,user,data,clock);db.commit()
            if result['claimed'] and not result['replayed']:EVENTS.publish()
            return Reply(200,{**result,'wallet':wallet.view(db,user['id'],clock),'server_time':clock})
        if path in ('/api/wallet/claim','/api/wallet/hourly'):
            if path.endswith('/hourly') and not isinstance(data.get('operation_id'),str):raise RuleError('缺少補給操作編號。')
            result=wallet.claim_hourly(db,user['id'],time.time(),data['operation_id']) if path.endswith('/hourly') else wallet.claim(db,user['id'],time.time())
            db.commit()
            EVENTS.publish()
            return Reply(200,{**result,'wallet':wallet.view(db,user['id'],time.time())})
        if path.startswith('/api/social/'):
            result=social.mutate(db,path,data,user,time.time())
            db.commit()
            rid=int(path.split('/')[4])
            EVENTS.publish(rid,lobby=False)
            return Reply(200,result)
        if path.startswith('/api/club/'):
            if not isinstance(data.get('operation_id'),str):raise RuleError('缺少操作編號。')
            result=online.mutate(db,path,data,user,time.time())
            if result.get('conflict'):raise Problem('操作編號與內容不符。',409)
            db.commit();EVENTS.publish()
            return Reply(200,{**result,'club':online.rewards.view(db,user['id'],time.time()),'wallet':wallet.view(db,user['id'],time.time())})
        if path.startswith("/api/online/"):
            result = online.mutate(db, path, data, user, time.time(), received_at=self.received_at)
            if result.get("conflict"):
                db.commit()  # A timeout processed by mutate must survive this 409.
                EVENTS.publish()
                reason = result.get("reason", "stale_version")
                messages = {"stale_settings":"遊戲賠率或機率已更新，請確認目前設定後重新開局。", "turn_expired":"這個回合已逾時，動作未接受。", "stale_turn":"下注回合已更新，這次動作未接受，請確認目前回合後再操作。", "stale_hand":"已開始新的一手，這次動作未接受。", "operation_mismatch":"操作編號與內容不符，請重新整理。"}
                raise Problem(messages.get(reason,"牌桌已更新，請確認最新狀態後操作。"),409,reason)
            lobby_changed=result.pop('_lobby_changed',True)
            committed = time.monotonic()
            db.commit()
            self.timings["commit"] = (time.monotonic()-committed)*1000
            EVENTS.publish(result['id'],lobby=lobby_changed)
            # Construct the authenticated private view only after do_POST has
            # released FIFO admission. No follow-up GET is needed by the actor.
            return Reply(200, {"ok": True, **result}, snapshot_room_id=result['id'])
        if path == "/api/logout":
            jar = SimpleCookie(self.headers.get("Cookie", ""))
            db.execute("DELETE FROM auth_sessions WHERE token_hash=?", (hashlib.sha256(jar["poker_session"].value.encode()).hexdigest(),))
            db.commit()
            EVENTS.publish()
            return Reply(200, {"ok": True}, cookie="poker_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0" + ("; Secure" if SECURE_COOKIE else ""))
            return
        if path == "/api/games":
            title = clean(data.get("title"), "牌局名称")
            date = clean(data.get("played_on"), "日期", 10)
            try:
                if datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d") != date:
                    raise ValueError()
            except ValueError:
                raise Problem("请填写有效日期（YYYY-MM-DD）。")
            unit = clean(data.get("unit"), "记账单位", 8)
            note = data.get("note", "")
            if not isinstance(note, str) or len(note) > 300:
                raise Problem("备注最多 300 个字。")
            ids = data.get("players")
            if not isinstance(ids, list) or not 2 <= len(ids) <= 6 or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids):
                raise Problem("请选择 2–6 位不同的成员。")
            known = {r[0] for r in db.execute("SELECT id FROM users")}
            if not set(ids) <= known or user["id"] not in ids:
                raise Problem("参与者需包含开局者，且都已注册。")
            buy_in = money(data.get("buy_in", "0"))
            game_id = db.execute("INSERT INTO games(title,played_on,unit,note,creator_id,status,created_at) VALUES(?,?,?,?,?,'active',?)",
                                 (title, date, unit, note.strip(), user["id"], now())).lastrowid
            db.executemany("INSERT INTO entries(game_id,user_id,buy_in) VALUES(?,?,?)", [(game_id, i, buy_in) for i in ids])
            audit(db, game_id, user["id"], "create", {"players": ids, "buy_in": buy_in})
            db.commit()
            return Reply(201, {"ok": True, "id": game_id})
        match = re.fullmatch(r"/api/games/(\d+)/(entries|settle|reopen|cancel)", path)
        if not match:
            raise Problem("操作不存在。", 404)
        game_id, action = int(match[1]), match[2]
        game = db.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        if not game:
            raise Problem("找不到这场牌局。", 404)
        if game["creator_id"] != user["id"]:
            raise Problem("只有这场牌局的开局者可以修改或结算。", 403)
        if type(data.get("revision")) is not int or game["revision"] != data["revision"]:
            raise Problem("牌局已被更新，请刷新后再操作。", 409)
        entries = [dict(r) for r in db.execute("SELECT * FROM entries WHERE game_id=?", (game_id,))]
        if action == "reopen":
            if game["status"] != "settled":
                raise Problem("只有已结算的牌局可以重新编辑。", 409)
            db.execute("UPDATE games SET status='active',settled_at=NULL WHERE id=?", (game_id,))
        else:
            if game["status"] != "active":
                raise Problem("这场牌局目前无法编辑。", 409)
            if action == "entries":
                values = data.get("entries")
                if not isinstance(values, list) or len(values) != len(entries):
                    raise Problem("请提交所有参与者的记录。")
                if any(not isinstance(e, dict) or type(e.get("user_id")) is not int for e in values):
                    raise Problem("参与者资料无效。")
                if len({e["user_id"] for e in values}) != len(values) or {e["user_id"] for e in values} != {e["user_id"] for e in entries}:
                    raise Problem("参与者资料不一致，请刷新后重试。")
                for e in values:
                    db.execute("UPDATE entries SET buy_in=?,cash_out=? WHERE game_id=? AND user_id=?",
                               (money(e.get("buy_in")), None if e.get("cash_out") is None else money(e["cash_out"]), game_id, e["user_id"]))
            elif action == "settle":
                if any(e["cash_out"] is None for e in entries):
                    raise Problem("请先填写并保存每位玩家的带出金额。")
                difference = sum(e["cash_out"]-e["buy_in"] for e in entries)
                if difference:
                    raise Problem(f"收支尚未平衡，相差 {abs(difference)/100:,.2f} {game['unit']}，请检查买入与带出。")
                db.execute("UPDATE games SET status='settled',settled_at=? WHERE id=?", (now(), game_id))
            else:
                db.execute("UPDATE games SET status='cancelled' WHERE id=?", (game_id,))
        audit(db, game_id, user["id"], action, {"before": entries, "request": data})
        db.execute("UPDATE games SET revision=revision+1 WHERE id=?", (game_id,))
        db.commit()
        return Reply(200, {"ok": True})


def main():
    parser = argparse.ArgumentParser(description="楠團德州撲克 · 六人私人線上牌室")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = parser.parse_args()
    initialize()
    try:
        server = GameHTTPServer((args.host, args.port), Handler)
        server.daemon_threads = False
    except OSError as ex:
        if args.open:
            # Double-clicking the launcher while the club is running just opens it.
            try:
                import urllib.request
                import webbrowser
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
                        f"http://127.0.0.1:{args.port}/api/bootstrap", timeout=2) as response:
                    existing = json.load(response)
                if existing.get("capacity") == 6:
                    webbrowser.open(f"http://127.0.0.1:{args.port}")
                    print("牌桌已经在运行，已为你打开浏览器。", flush=True)
                    return
            except Exception:
                pass
        print(f"无法启动：{ex}。若已启动，请打开 http://localhost:{args.port}", flush=True)
        raise SystemExit(1)
    print(f"楠團德州扑克已启动：http://localhost:{args.port}\n数据库：{DB_PATH}\n关闭此窗口将停止服务。", flush=True)
    try:
        ips = set(socket.gethostbyname_ex(socket.gethostname())[2])
        for ip in sorted(ips):
            if not ip.startswith("127."):
                print(f"同一 Wi-Fi 手机连接：http://{ip}:{args.port}", flush=True)
    except OSError:
        pass
    if args.open:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(f"http://localhost:{args.port}")).start()
    # Docker sends SIGTERM. Shutdown on a separate thread so serve_forever can exit.
    def shutdown(*_):
        EVENTS.stop()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    stopping = threading.Event()
    def dealer_clock():
        while not stopping.wait(1):
            try:
                with WRITES.enter() as admission:
                    with connect() as db:
                        db.execute("BEGIN IMMEDIATE")
                        changed = online.maintenance(db, due_at=admission.received_at)
                if changed:
                    EVENTS.publish()
            except Exception as error:
                print("Dealer clock:", type(error).__name__, str(error), flush=True)
    threading.Thread(target=dealer_clock, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopping.set()
        EVENTS.stop()
        server.server_close()


if __name__ == "__main__":
    main()
