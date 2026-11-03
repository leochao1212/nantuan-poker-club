"""Read-only service watchdog. Run on leoserver; emits compact transition reports.

No credentials, player records, restart commands or outbound notifications.
Exit 1 on a failed one-shot check; use --watch for one check per minute.
"""
import argparse
import json
import subprocess
import time


def probe(url):
    started = time.monotonic()
    try:
        response = subprocess.run(['curl', '--noproxy', '*', '-fsS', '--max-time', '8', url],
                                  capture_output=True, timeout=10)
        ok = response.returncode == 0 and json.loads(response.stdout).get('ok') is True
    except (OSError, subprocess.TimeoutExpired, ValueError):
        ok = False
    return dict(ok=ok, ms=round((time.monotonic()-started)*1000))


def check():
    try:
        result = subprocess.run(['docker', 'inspect', '--format', '{{json .State}}', 'boyband-poker'],
                                capture_output=True, timeout=10, check=True)
        state = json.loads(result.stdout)
        container = state.get('Running') and state.get('Health', {}).get('Status') == 'healthy'
    except (OSError, ValueError, subprocess.SubprocessError):
        container = False
    local = probe('http://127.0.0.1:8765/api/health')
    public = probe('https://poker.leoapi.dpdns.org/api/health')
    return dict(at=int(time.time()), container=bool(container), local=local, public=public,
                ok=bool(container and local['ok'] and public['ok']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    previous = None
    failures = 0
    while True:
        result = check()
        failures = 0 if result['ok'] else failures+1
        result['consecutive_failures'] = failures
        signature = (result['container'], result['local']['ok'], result['public']['ok'])
        if signature != previous or failures == 3 or not args.watch:
            print(json.dumps(result), flush=True)
        previous = signature
        if not args.watch:
            return 0 if result['ok'] else 1
        time.sleep(60)


if __name__ == '__main__':
    raise SystemExit(main())
