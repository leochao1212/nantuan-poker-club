"""Bounded authenticated PCM speech relay. Audio is transient and never persisted.

One 40 ms, 16 kHz mono PCM16 frame is relayed independently of game queues/SSE.
Slow listeners lose old frames rather than blocking speakers or growing memory.
"""
import base64
import hashlib
import json
import queue
import socket
import select
import struct
import threading
import time

FRAME_BYTES = 1280
MAX_PEERS = 48
MAX_ROOM = 24


class Peer:
    def __init__(self, uid, room, session, sock):
        self.uid, self.room, self.session, self.sock = uid, room, session, sock
        self.queue = queue.Queue(maxsize=8)
        self.stopped = threading.Event()
        self.muted = False
        self.ready = False
        self.controls = queue.Queue(maxsize=4)
        self.pending = b''

    def stop(self):
        self.stopped.set()
        try:self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:pass


class Relay:
    def __init__(self):
        self.lock = threading.Lock()
        self.peers = {}
        self.wake = threading.Event()
        self.writer = None

    def add(self, peer):
        with self.lock:
            old = self.peers.get(peer.uid)
            if len(self.peers) - int(old is not None) >= MAX_PEERS:
                raise ValueError('語音使用人數已滿，請稍後再試。')
            if sum(p.room == peer.room and p.uid != peer.uid for p in self.peers.values()) >= MAX_ROOM:
                raise ValueError('這個語音房已滿，請選擇另一個語音房。')
            self.peers[peer.uid] = peer
            if self.writer is None:
                self.writer=threading.Thread(target=self.send_loop,daemon=True)
                self.writer.start()
        if old:old.stop()

    def control(self,peer,payload,opcode):
        try:peer.controls.put_nowait(frame_bytes(payload,opcode))
        except queue.Full:
            peer.stop();return
        self.wake.set()

    def send_loop(self):
        # One writer batches all listeners, avoiding a GIL/thread handoff per
        # listener per audio frame. Only writable sockets are touched.
        while True:
            self.wake.wait(.02);self.wake.clear()
            with self.lock:
                if not self.peers:self.writer=None;return
                peers=[p for p in self.peers.values() if p.ready and not p.stopped.is_set() and (p.pending or not p.controls.empty() or not p.queue.empty())]
            if not peers:continue
            try:_,writable,_=select.select([], [p.sock for p in peers], [], 0)
            except (OSError,ValueError):continue
            if not writable:continue
            ready=set(writable)
            for p in peers:
                if p.sock not in ready or p.stopped.is_set():continue
                if not p.pending:
                    parts=[]
                    for _ in range(4):
                        try:parts.append(p.controls.get_nowait())
                        except queue.Empty:break
                    for _ in range(4):
                        try:parts.append(frame_bytes(p.queue.get_nowait()))
                        except queue.Empty:break
                    p.pending=b''.join(parts)
                if not p.pending:continue
                try:
                    sent=p.sock.send(p.pending)
                    if not sent:p.stop()
                    else:p.pending=p.pending[sent:]
                except (OSError,ValueError):p.stop()
            if any(p.sock in ready and not p.stopped.is_set() and (p.pending or not p.queue.empty() or not p.controls.empty()) for p in peers):self.wake.set()

    def remove(self, peer):
        with self.lock:
            if self.peers.get(peer.uid) is peer:self.peers.pop(peer.uid, None)
        peer.stop()

    def online(self, room):
        with self.lock:return [p.uid for p in self.peers.values() if p.room == room and not p.stopped.is_set()]

    def sessions(self):
        with self.lock:return [(p.room,p.uid,p.session) for p in self.peers.values() if not p.stopped.is_set()]

    def broadcast(self, peer, pcm):
        packet = struct.pack('!I', peer.uid) + pcm
        with self.lock:
            if self.peers.get(peer.uid) is not peer:return
            targets = [p for p in self.peers.values() if p.room == peer.room and p is not peer and not p.stopped.is_set()]
        for target in targets:
            try:target.queue.put_nowait(packet)
            except queue.Full:
                try:target.queue.get_nowait()
                except queue.Empty:pass
                try:target.queue.put_nowait(packet)
                except queue.Full:pass
        self.wake.set()


HUB = Relay()


def read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        part = stream.read(size - len(data))
        if not part:raise EOFError()
        data.extend(part)
    return bytes(data)


def read_frame(stream):
    first, second = read_exact(stream, 2)
    opcode = first & 15
    if not first & 128 or first & 112 or not second & 128:
        raise ValueError('Unsupported or unmasked WebSocket frame')
    length = second & 127
    if length == 126:length = struct.unpack('!H', read_exact(stream, 2))[0]
    elif length == 127:length = struct.unpack('!Q', read_exact(stream, 8))[0]
    if length > 2048 or opcode not in (1, 2, 8, 9, 10) or opcode >= 8 and length > 125:
        raise ValueError('Voice frame exceeds allowed size')
    mask = read_exact(stream, 4)
    payload = read_exact(stream, length)
    return opcode, bytes(value ^ mask[i % 4] for i, value in enumerate(payload))


def frame_bytes(payload,opcode=2):
    length=len(payload)
    header=bytes([128|opcode,length]) if length<126 else bytes([128|opcode,126])+struct.pack('!H',length)
    return header+payload


def write_frame(sock,payload,opcode=2):
    sock.sendall(frame_bytes(payload,opcode))


def serve(handler, uid, room, session, authorize):
    """Called after HTTP auth, origin, membership and handshake validation."""
    key = handler.headers.get('Sec-WebSocket-Key', '')
    try:valid = len(base64.b64decode(key, validate=True)) == 16
    except ValueError:valid = False
    if not valid or handler.headers.get('Sec-WebSocket-Version') != '13':raise ValueError('Invalid WebSocket handshake')
    if handler.headers.get('Upgrade', '').lower() != 'websocket' or 'upgrade' not in handler.headers.get('Connection', '').lower():
        raise ValueError('WebSocket upgrade required')
    peer = Peer(uid, room, session, handler.connection)
    HUB.add(peer)
    writer = None
    try:
        accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        handler.protocol_version = 'HTTP/1.1'
        handler.send_response(101)
        handler.send_header('Upgrade', 'websocket');handler.send_header('Connection', 'Upgrade')
        handler.send_header('Sec-WebSocket-Accept', accept);handler.end_headers();handler.wfile.flush()
        handler.close_connection = True
        handler.connection.settimeout(12)
        peer.ready=True
        def send_loop():
            last_ping = last_auth = time.monotonic()
            try:
                HUB.control(peer, b'{"type":"ready","sampleRate":16000,"frameSamples":640}', 1)
                while not peer.stopped.is_set():
                    peer.stopped.wait(.2)
                    now = time.monotonic()
                    if now - last_auth >= 5:
                        if not authorize():
                            HUB.control(peer, struct.pack('!H', 1008), 8);break
                        last_auth = now
                    if now - last_ping >= 4:HUB.control(peer, b'v', 9);last_ping = now
            except (OSError, ValueError):pass
            finally:peer.stop()
        writer = threading.Thread(target=send_loop, daemon=True);writer.start()
        allowance = 35.0;last = time.monotonic();controls = 15.0;last_control = last
        while not peer.stopped.is_set():
            opcode, payload = read_frame(handler.rfile)
            if opcode == 8:break
            if opcode in (9, 10):continue
            if opcode == 1:
                now=time.monotonic();controls=min(15,controls+(now-last_control)*2);last_control=now
                if controls<1:raise ValueError('Voice control rate exceeded')
                controls-=1
                control = json.loads(payload)
                if not isinstance(control, dict) or set(control) != {'muted'} or not isinstance(control['muted'], bool):raise ValueError('Invalid voice control')
                peer.muted = control['muted'];continue
            now = time.monotonic();allowance = min(35, allowance + (now - last) * 27);last = now
            if len(payload) != FRAME_BYTES or allowance < 1:raise ValueError('Voice frame rate or size exceeded')
            allowance -= 1
            if not peer.muted:HUB.broadcast(peer, payload)
    except (OSError, EOFError, ValueError):pass
    finally:
        HUB.remove(peer)
        if writer:writer.join(timeout=1)
