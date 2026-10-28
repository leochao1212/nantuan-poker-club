"""Bounded transient battle rooms and authenticated WebSocket transport.

Entirely separate from SQLite writes, card-table SSE and wallet settlement.
One simulation thread, one replaceable snapshot per peer, bounded room lifetime.
"""
import base64
from collections import deque
from dataclasses import dataclass, field
import hashlib
import json
import queue
import secrets
import socket
import struct
import threading
import time

from battle_engine import Match, STEP, CAPACITY, WEAPONS
from voice_transport import read_frame

MAX_ROOMS=3
MAX_PEERS=32
MAX_TITLE=32


@dataclass
class Room:
    code: str
    title: str
    host: int
    match: Match
    touched: float
    bots: bool = True
    last_snapshot: float = 0


class Peer:
    def __init__(self,uid,code,sock):
        self.uid=uid;self.code=code;self.sock=sock
        self.snapshots=queue.Queue(maxsize=1);self.controls=queue.Queue(maxsize=8)
        self.stopped=threading.Event()

    def control(self,payload,opcode=1):
        try:self.controls.put_nowait((opcode,payload))
        except queue.Full:self.stop()

    def close(self,code=1000):
        self.control(struct.pack('!H',code),8)

    def snapshot(self,value):
        try:self.snapshots.put_nowait(value)
        except queue.Full:
            try:self.snapshots.get_nowait()
            except queue.Empty:pass
            try:self.snapshots.put_nowait(value)
            except queue.Full:pass

    def stop(self):
        self.stopped.set()
        try:self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:pass


def pack(payload,opcode=1):
    if not isinstance(payload,bytes):payload=json.dumps(payload,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
    n=len(payload)
    head=bytes([128|opcode,n]) if n<126 else bytes([128|opcode,126])+struct.pack('!H',n) if n<=65535 else bytes([128|opcode,127])+struct.pack('!Q',n)
    return head+payload


class BattleHub:
    def __init__(self,run=True):
        self.lock=threading.RLock();self.rooms={};self.peers={};self.members={}
        self.stopping=threading.Event();self.wake=threading.Event();self.thread=None;self.run=run
        self.budget={};self.metrics=dict(ticks=0,max_tick_ms=0.,snapshots=0)

    def ensure_worker(self):
        if self.run and (self.thread is None or not self.thread.is_alive()):
            self.thread=threading.Thread(target=self.loop,daemon=True,name='island-simulation');self.thread.start()
        self.wake.set()

    def list(self,uid):
        with self.lock:
            return dict(current=self.members.get(uid),capacity=CAPACITY,rooms=[dict(code=r.code,title=r.title,host=r.host,
                    players=[dict(id=p.id,name=p.name,connected=p.connected) for p in r.match.players.values() if not p.bot],
                    humans=sum(not p.bot for p in r.match.players.values()),phase=r.match.phase,bots=r.bots)
                    for r in self.rooms.values()],weapons=WEAPONS)

    def create(self,uid,name,title='',bots=True):
        with self.lock:
            # Retrying an uncertain creation returns the same membership, never another room.
            if uid in self.members:return dict(code=self.members[uid])
            if not isinstance(bots,bool):raise ValueError('AI 補位設定無效。')
            if not isinstance(title,str) or len(title.strip())>MAX_TITLE:raise ValueError('房名最多 32 個字。')
            now=time.monotonic();self.cleanup(now)
            if len(self.rooms)>=MAX_ROOMS:raise ValueError('目前戰場已滿，請加入現有房間或稍後再開。')
            if len(self.members)>=MAX_PEERS:raise ValueError('目前戰場人數已滿。')
            recent=[t for t in self.budget.get(uid,[]) if now-t<60]
            if len(recent)>=3:raise ValueError('開房太頻繁，請稍候一分鐘。')
            self.budget={k:v for k,v in self.budget.items() if v and now-v[-1]<60};self.budget[uid]=recent+[now]
            code=secrets.token_hex(3).upper()
            while code in self.rooms:code=secrets.token_hex(3).upper()
            match=Match(secrets.randbits(31),now);match.add(uid,name)
            self.rooms[code]=Room(code,title.strip() or name+'的戰場',uid,match,now,bots)
            self.members[uid]=code;self.ensure_worker()
            return dict(code=code)

    def join(self,uid,name,code):
        if not isinstance(code,str):raise ValueError('請填寫六位房號。')
        code=code.strip().upper()
        with self.lock:
            if uid in self.members:
                if self.members[uid]==code:return dict(code=code)
                raise ValueError('請先離開目前的戰場。')
            if len(self.members)>=MAX_PEERS:raise ValueError('目前戰場人數已滿。')
            if code not in self.rooms:raise ValueError('找不到這個戰場，可能已結束。')
            r=self.rooms[code];r.match.add(uid,name);r.touched=time.monotonic();self.members[uid]=code
            self.ensure_worker();return dict(code=code)

    def leave(self,uid):
        with self.lock:
            code=self.members.pop(uid,None);r=self.rooms.get(code)
            peer=self.peers.pop(uid,None)
            if peer:peer.close()
            if r and uid in r.match.players:
                if r.match.phase in ('waiting','finished'):r.match.players.pop(uid)
                else:r.match.damage(r.match.players[uid],1000,source='leave')
                humans=[p.id for p in r.match.players.values() if not p.bot and p.id in self.members]
                if r.host==uid:r.host=humans[0] if humans else 0
                if not humans:self.rooms.pop(code,None)
            return dict(ok=True)

    def attach(self,peer):
        with self.lock:
            if self.members.get(peer.uid)!=peer.code or peer.code not in self.rooms:raise ValueError('請先加入戰場。')
            if len(self.peers)>=MAX_PEERS and peer.uid not in self.peers:raise ValueError('戰場連線已滿。')
            r=self.rooms[peer.code];old=self.peers.get(peer.uid)
            if old:old.close(4001)
            self.peers[peer.uid]=peer;p=r.match.players[peer.uid];p.connected=True;p.gone_at=None;p.seq=-1;p.intent={}
            peer.control(dict(type='welcome',room=peer.code,title=r.title,host=r.host,bots=r.bots,
                              map=r.match.map,weapons=WEAPONS,roster=[dict(id=p.id,name=p.name,bot=p.bot) for p in r.match.players.values()]))
            peer.snapshot(self.view(r,peer.uid));self.ensure_worker()

    def detach(self,peer):
        with self.lock:
            if self.peers.get(peer.uid) is not peer:return
            self.peers.pop(peer.uid,None);r=self.rooms.get(peer.code)
            if r and peer.uid in r.match.players:
                p=r.match.players[peer.uid];p.connected=False;p.gone_at=time.monotonic();p.intent={}
        peer.stop()

    def handle(self,peer,data):
        if not isinstance(data,dict):raise ValueError('無效的戰場訊息。')
        with self.lock:
            if self.peers.get(peer.uid) is not peer:return
            r=self.rooms.get(peer.code)
            if not r or self.members.get(peer.uid)!=r.code:raise ValueError('你已離開這個戰場。')
            now=time.monotonic()
            if data.get('type')!='ping':r.touched=now
            if data.get('type')=='input':r.match.input(peer.uid,data,now)
            elif data.get('type')=='ping':peer.control(dict(type='pong',echo=data.get('echo') if isinstance(data.get('echo'),(int,float)) else 0))
            elif data.get('type')=='action':
                if set(data)-{'type','action','value'}:raise ValueError('無效的戰場動作。')
                kind=data.get('action')
                if kind=='start':
                    if r.host!=peer.uid:raise ValueError('只有房主可以開始。')
                    r.match.start(now,r.bots)
                elif kind=='reset':
                    if r.host!=peer.uid or r.match.phase!='finished':raise ValueError('這局尚未結束，或你不是房主。')
                    humans=[p for p in r.match.players.values() if not p.bot and self.members.get(p.id)==r.code]
                    r.match=Match(secrets.randbits(31),now)
                    for p in humans:r.match.add(p.id,p.name).connected=p.id in self.peers
                    for p in self.peers.values():
                        if p.code==r.code:p.control(dict(type='map',map=r.match.map))
                else:r.match.action(peer.uid,kind,data.get('value'))
            else:raise ValueError('不支援的戰場訊息。')

    def view(self,r,uid):
        return {**r.match.snapshot(uid),'room':r.code,'host':r.host,'title':r.title,'bots':r.bots}

    def cleanup(self,now):
        for code,r in list(self.rooms.items()):
            for p in list(r.match.players.values()):
                if p.bot:continue
                if p.id not in self.peers and p.gone_at is None:p.gone_at=r.touched;p.connected=False
                if r.match.phase=='waiting' and p.gone_at is not None and now-p.gone_at>90:
                    r.match.players.pop(p.id);self.members.pop(p.id,None)
            humans=[p.id for p in r.match.players.values() if not p.bot and self.members.get(p.id)==code]
            if r.host not in humans:r.host=humans[0] if humans else 0
            expired=not humans or now-r.touched>600 or r.match.phase=='finished' and now-r.match.ended>180
            if expired:
                self.rooms.pop(code,None)
                for uid,member in list(self.members.items()):
                    if member==code:
                        self.members.pop(uid,None);p=self.peers.pop(uid,None)
                        if p:p.close(4004)

    def step(self,now):
        batches=[];started=time.perf_counter()
        with self.lock:
            self.cleanup(now)
            for r in self.rooms.values():
                r.match.advance(now)
                if now-r.last_snapshot>=.12:
                    r.last_snapshot=now
                    for uid,peer in self.peers.items():
                        if peer.code==r.code and uid in r.match.players:batches.append((peer,self.view(r,uid)))
            self.metrics['ticks']+=1
            self.metrics['max_tick_ms']=max(self.metrics['max_tick_ms'],(time.perf_counter()-started)*1000)
        for peer,state in batches:
            peer.snapshot(state);self.metrics['snapshots']+=1

    def loop(self):
        while not self.stopping.is_set():
            before=time.monotonic()
            try:self.step(before)
            except Exception as ex:print('island_tick_error',type(ex).__name__,flush=True)
            delay=max(.005,STEP-(time.monotonic()-before)) if self.rooms else 1
            self.wake.wait(delay);self.wake.clear()

    def stop(self):
        self.stopping.set();self.wake.set()
        for p in list(self.peers.values()):p.stop()
        if self.thread:self.thread.join(2)


HUB=BattleHub()


def serve(handler,uid,code,authorize):
    """HTTP layer has already checked session, account state, origin and room."""
    key=handler.headers.get('Sec-WebSocket-Key','')
    try:valid=len(base64.b64decode(key,validate=True))==16
    except ValueError:valid=False
    if not valid or handler.headers.get('Sec-WebSocket-Version')!='13':raise ValueError('Invalid battle WebSocket handshake')
    if handler.headers.get('Upgrade','').lower()!='websocket' or 'upgrade' not in handler.headers.get('Connection','').lower():
        raise ValueError('WebSocket upgrade required')
    peer=Peer(uid,code,handler.connection)
    # Reserve/check membership before sending an upgrade; attach also replaces old tabs.
    with HUB.lock:
        if HUB.members.get(uid)!=code or code not in HUB.rooms:raise ValueError('請先加入戰場。')
    accept=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
    handler.protocol_version='HTTP/1.1';handler.send_response(101)
    handler.send_header('Upgrade','websocket');handler.send_header('Connection','Upgrade');handler.send_header('Sec-WebSocket-Accept',accept)
    handler.end_headers();handler.wfile.flush();handler.close_connection=True;handler.connection.settimeout(7)
    def writer():
        last_ping=last_auth=time.monotonic()
        try:
            while not peer.stopped.is_set():
                now=time.monotonic()
                if now-last_auth>=5:
                    if not authorize():peer.sock.sendall(pack(struct.pack('!H',4003),8));return
                    last_auth=now
                if now-last_ping>=2.5:peer.sock.sendall(pack(b'b',9));last_ping=now
                try:
                    opcode,payload=peer.controls.get_nowait();peer.sock.sendall(pack(payload,opcode))
                    if opcode==8:return
                    continue
                except queue.Empty:pass
                try:state=peer.snapshots.get(timeout=.05)
                except queue.Empty:continue
                peer.sock.sendall(pack(state))
        except (OSError,ValueError):pass
        finally:peer.stop()
    sender=None
    try:
        HUB.attach(peer);sender=threading.Thread(target=writer,daemon=True,name='island-send');sender.start()
        allowance=75.;controls=10.;last=time.monotonic()
        while not peer.stopped.is_set():
            opcode,payload=read_frame(handler.rfile)
            if opcode==8:break
            if opcode==10:continue
            if opcode==9:peer.control(payload,10);continue
            if opcode!=1:raise ValueError('Battle accepts text input only')
            now=time.monotonic();elapsed=now-last;last=now
            allowance=min(75,allowance+elapsed*35);controls=min(10,controls+elapsed*5)
            if allowance<1:raise ValueError('Input rate exceeded')
            allowance-=1;data=json.loads(payload)
            if not isinstance(data,dict):raise ValueError('Invalid input')
            if data.get('type')!='input':
                if controls<1:raise ValueError('Action rate exceeded')
                controls-=1
            try:HUB.handle(peer,data)
            except (ValueError,KeyError,TypeError) as ex:
                peer.control(dict(type='error',message=str(ex) if isinstance(ex,ValueError) else '戰場操作無效。'))
    except (OSError,EOFError,ValueError):pass
    finally:
        HUB.detach(peer);peer.stop()
        if sender:sender.join(1)
