"""Wake authenticated SSE subscribers after committed changes; no private state in the hub."""
from contextlib import contextmanager
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Admission:
    received_at: float
    queue_ms: float


class WriteQueue:
    """FIFO admission shared by actions, snapshots and dealer timeouts.

    Timestamp and ticket are assigned atomically, before waiting for SQLite.
    A later timeout can never overtake a previously admitted player action.
    Network writes must happen outside this context.
    """
    def __init__(self):
        self.condition = threading.Condition()
        self.next_ticket = self.serving = 0

    @contextmanager
    def enter(self):
        with self.condition:
            ticket = self.next_ticket
            self.next_ticket += 1
            received_at, started = time.time(), time.monotonic()
            self.condition.wait_for(lambda: ticket == self.serving)
        try:
            yield Admission(received_at, (time.monotonic()-started)*1000)
        finally:
            with self.condition:
                self.serving += 1
                self.condition.notify_all()


class Hub:
    def __init__(self):
        self.condition = threading.Condition()
        self.version = 0
        self.channels = {}
        self.stopped = False
        self.clients = {}
        self.sessions = {}

    @contextmanager
    def subscribe(self, uid, client_id=None):
        # One browser page keeps its identity when switching room channels.
        # Replacement cancels its old lease without consuming another slot.
        key = (uid, client_id) if client_id is not None else None
        lease = threading.Event()
        with self.condition:
            old = self.sessions.get(key) if key is not None else None
            replacing = int(old is not None)
            if self.clients.get(uid, 0)-replacing >= 5 or sum(self.clients.values())-replacing >= 80:
                raise ValueError("請關閉多餘的牌室分頁，再重新連線。")
            if old is not None:
                old.set()
            self.clients[uid] = self.clients.get(uid, 0)+1-replacing
            if key is not None:
                self.sessions[key] = lease
            self.condition.notify_all()
        try:
            yield lease
        finally:
            with self.condition:
                # A replaced lease must not remove its successor's reservation.
                if key is None or self.sessions.get(key) is lease:
                    if key is not None:
                        del self.sessions[key]
                    self.clients[uid] -= 1
                    if not self.clients[uid]:
                        del self.clients[uid]

    def publish(self,room_id=None,lobby=True):
        with self.condition:
            if room_id is None:self.version+=1
            else:
                self.channels[room_id]=self.channels.get(room_id,0)+1
                if lobby:self.channels[0]=self.channels.get(0,0)+1
            self.condition.notify_all()

    def version_for(self,room_id=None):
        with self.condition:return (self.version,self.channels.get(room_id or 0,0))

    def wait(self,version,timeout=10,room_id=None,cancelled=None):
        with self.condition:
            self.condition.wait_for(lambda:self.stopped or cancelled is not None and cancelled.is_set() or (self.version,self.channels.get(room_id or 0,0))!=version,timeout)
            return (self.version,self.channels.get(room_id or 0,0))

    def stop(self):
        with self.condition:
            self.stopped = True
            self.condition.notify_all()
