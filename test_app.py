"""End-to-end API tests; never touch the real club database."""
import concurrent.futures
from contextlib import closing
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, path, data=None, origin=None):
        headers = {"X-Requested-With": "PokerClub", "Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(self.base+path, None if data is None else json.dumps(data).encode(), headers)
        try:
            response = self.opener.open(req, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
        if response.headers.get_content_type() == "application/json":
            raw = json.loads(raw)
        return response.status, raw


class ServerTestCase(unittest.TestCase):
    server_env = {}

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{port}"
        cls.db_path = Path(cls.tmp.name)/"test.sqlite3"
        env = dict(os.environ, POKER_DB=str(cls.db_path), PYTHONIOENCODING="utf-8", POKER_SECURE_COOKIE="0", POKER_REQUIRE_INVITE="0", POKER_PUBLIC_ORIGIN="")
        env.update(cls.server_env)
        cls.proc = subprocess.Popen([sys.executable, str(ROOT/"server.py"), "--host", "127.0.0.1", "--port", str(port)],
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.clients = [Client(cls.base) for _ in range(8)]
        for _ in range(100):
            try:
                cls.clients[0].call("/api/bootstrap")
                break
            except OSError:
                time.sleep(.05)
        else:
            cls.proc.terminate()
            raise RuntimeError("Test server failed to start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.tmp.cleanup()


class PokerFlow(ServerTestCase):
    def test_complete_six_member_flow(self):
        a = self.clients[0]
        self.assertEqual(a.call("/api/state")[0], 401)
        self.assertEqual(a.call("/api/bootstrap")[1]["member_count"], 0)
        self.assertEqual(a.call("/../server.py")[0], 404)
        self.assertEqual(a.call("/")[0], 200)
        self.assertEqual(a.call("/api/register", {"username":"player1","nickname":"大哥","password":"password123"})[0], 200)
        code = a.call("/api/state")[1]["invite_code"]
        b = self.clients[1]
        self.assertEqual(b.call("/api/register", {"username":"player2","nickname":"二哥","password":"password123","invite_code":"wrong"})[0], 403)
        for i in range(1,6):
            self.assertEqual(self.clients[i].call("/api/register", {"username":f"player{i+1}","nickname":f"兄弟{i+1}","password":"password123","invite_code":code})[0], 200)
        self.assertEqual(self.clients[6].call("/api/register", {"username":"seventh","nickname":"第七人","password":"password123","invite_code":code})[0], 200)
        self.assertEqual(b.call("/api/games", {"title":"test"}, origin="http://evil.invalid")[0], 403)
        payload={"title":"测试兄弟局", "played_on":"2026-10-20","unit":"筹码","buy_in":"1000.10","players":[1,2,3,4,5,6],"note":"小盲 5 / 大盲 10"}
        self.assertEqual(a.call("/api/games", dict(payload, players=[1]))[0], 400)
        self.assertEqual(a.call("/api/games", dict(payload, players=[1,1]))[0], 400)
        self.assertEqual(a.call("/api/games", dict(payload, buy_in="NaN"))[0], 400)
        self.assertEqual(a.call("/api/games", dict(payload, buy_in="1.001"))[0], 400)
        self.assertEqual(a.call("/api/games", dict(payload, played_on="2026-02-30"))[0], 400)
        status, body = a.call("/api/games", payload)
        self.assertEqual(status, 201)
        gid = body["id"]
        path = f"/api/games/{gid}"
        self.assertEqual(b.call(path+"/settle", {"revision":1})[0], 403)
        self.assertEqual(a.call(path+"/settle", {"revision":1})[0], 400) # Missing cash-outs.
        values=[{"user_id":i,"buy_in":"1000.10","cash_out":"1000.10"} for i in range(1,7)]
        values[0]["cash_out"]="1500.11"
        values[1]["cash_out"]="500.10" # Deliberate one-cent mismatch.
        self.assertEqual(a.call(path+"/entries", {"revision":1,"entries":values})[0], 200)
        self.assertEqual(a.call(path+"/settle", {"revision":1})[0], 409) # Stale version.
        self.assertEqual(a.call(path+"/settle", {"revision":2})[0], 400) # Unbalanced.
        values[1]["cash_out"]="500.09"
        self.assertEqual(a.call(path+"/entries", {"revision":2,"entries":values})[0], 200)
        # Simultaneous saves must not overwrite each other.
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda _: a.call(path+"/entries", {"revision":3,"entries":values})[0], range(2)))
        self.assertEqual(sorted(results), [200,409])
        self.assertEqual(a.call(path+"/settle", {"revision":4})[0], 200)
        game = a.call("/api/state")[1]["games"][0]
        self.assertEqual(game["status"], "settled")
        self.assertEqual(game["entries"][0]["cash_out"]-game["entries"][0]["buy_in"], 50001)
        self.assertEqual(sum(e["cash_out"]-e["buy_in"] for e in game["entries"]), 0)
        self.assertEqual(a.call(path+"/entries", {"revision":5,"entries":values})[0], 409)
        csv = a.call("/api/export")[1].decode("utf-8-sig")
        self.assertIn("测试兄弟局", csv)
        self.assertIn("500.01", csv)
        self.assertNotIn("password", str(a.call("/api/state")[1]))
        self.assertEqual(a.call(path+"/reopen", {"revision":5})[0], 200)
        self.assertEqual(a.call("/api/state")[1]["games"][0]["status"], "active")
        self.assertEqual(a.call(path+"/settle", {"revision":6})[0], 200)
        self.assertEqual(a.call("/api/logout", {})[0], 200)
        self.assertEqual(a.call("/api/state")[0], 401)
        self.assertEqual(a.call("/api/login", {"username":"PLAYER1","password":"password123"})[0], 200)
        # Negative, missing, and invalid money must not partially save valid earlier rows.
        draft_id = a.call("/api/games", dict(payload,title="作废测试"))[1]["id"]
        bad = [dict(e) for e in values]
        bad[0]["buy_in"]="999"
        bad[-1]["cash_out"]="-1"
        self.assertEqual(a.call(f"/api/games/{draft_id}/entries", {"revision":1,"entries":bad})[0], 400)
        current=a.call("/api/state")[1]["games"][0]
        self.assertEqual(current["entries"][0]["buy_in"], 100010)
        self.assertEqual(a.call(f"/api/games/{draft_id}/cancel", {"revision":1})[0], 200)
        self.assertEqual(len(a.call("/api/state")[1]["games"]), 1)


class InviteOnlyFlow(ServerTestCase):
    server_env = {"POKER_REQUIRE_INVITE": "1", "POKER_PUBLIC_ORIGIN": "https://poker.leoapi.dpdns.org"}

    def test_first_member_requires_invite(self):
        client = self.clients[0]
        info = client.call("/api/bootstrap")[1]
        self.assertTrue(info["requires_invite"])
        self.assertEqual(info["member_count"], 0)
        self.assertNotIn("invite_code", info)
        payload = {"username": "first_member", "nickname": "First member", "password": "PreviewOnly123"}
        self.assertEqual(client.call("/api/register", payload)[0], 403)
        self.assertEqual(client.call("/api/register", dict(payload, invite_code="WRONG"))[0], 403)
        with closing(sqlite3.connect(self.db_path)) as db:
            code = db.execute("SELECT value FROM settings WHERE key='invite_code'").fetchone()[0]
        self.assertEqual(client.call("/api/register", dict(payload, invite_code=code), origin="https://poker.leoapi.dpdns.org")[0], 200)
        self.assertEqual(client.call("/api/state")[0], 200)
        self.assertEqual(client.call("/api/logout", {})[0], 200)
        self.assertTrue(client.call("/api/bootstrap")[1]["requires_invite"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
