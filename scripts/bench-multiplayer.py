"""Isolated multi-table HTTP/SSE benchmark; no production URLs or data accepted."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.python.test_app import ServerTestCase, Client
from tests.python.test_realtime import Stream


def run(count):
    ServerTestCase.setUpClass()
    try:
        clients = [Client(ServerTestCase.base) for _ in range(count)]
        invite = None
        for i, c in enumerate(clients):
            status, _ = c.call('/api/register', dict(username=f'load{i}', nickname=f'Load{i}', password='SyntheticLoad123', invite_code=invite))
            assert status == 200, status
            if invite is None: invite = c.call('/api/state')[1]['invite_code']
        rooms = []
        for offset in range(0, count, 6):
            members = clients[offset:offset+6]
            status, created = members[0].call('/api/online/rooms', dict(name='Load table', game_type='holdem'))
            assert status == 200, status
            path = '/api/online/rooms/'+str(created['id'])
            for c in members[1:]:
                status, _ = c.call(path+'/join', dict(revision=c.call(path)[1]['revision']))
                assert status == 200, status
            rooms.append((created['id'], path, members))
        with ExitStack() as stack:
            watchers = {}
            for rid, path, members in rooms:
                watchers[rid] = [stack.enter_context(closing(Stream(c, f'/api/online/events?presence=client&room={rid}'))) for c in members]
                for stream in watchers[rid]: stream.state()
            def start(room):
                rid, path, members = room
                begin = time.perf_counter()
                status, result = members[0].call(path+'/start', dict(revision=members[0].call(path)[1]['revision'], operation_id=f'benchmark_start_{rid:08d}'))
                assert status == 200, status
                for stream in watchers[rid]: stream.state(result['state']['revision'])
                return (time.perf_counter()-begin)*1000
            def interact(c):
                values = []
                for _ in range(4):
                    begin = time.perf_counter()
                    status, _ = c.call('/api/online/presence', {})
                    assert status == 200, status
                    status, _ = c.call('/api/bank')
                    assert status == 200, status
                    values.append((time.perf_counter()-begin)*1000)
                return values
            with ThreadPoolExecutor(count+len(rooms)) as pool:
                actions = [pool.submit(start, room) for room in rooms]
                reads = [pool.submit(interact, c) for c in clients]
                sync = [f.result() for f in actions]
                requests = sorted(v for f in reads for v in f.result())
            return dict(players=count, rooms=len(rooms), sse=count, samples=len(requests),
                presence_plus_bank_ms=dict(median=round(statistics.median(requests),1), p95=round(requests[int((len(requests)-1)*.95)],1)),
                start_and_all_room_push_max_ms=round(max(sync),1), failed_requests=0,
                scope='local synthetic HTTP/SSE; excludes public internet, voice and real device rendering')
    finally:
        ServerTestCase.tearDownClass()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--players', nargs='+', type=int, choices=(10,20,40), default=[10,20,40])
    args = parser.parse_args()
    for count in args.players: print(json.dumps(run(count)), flush=True)
