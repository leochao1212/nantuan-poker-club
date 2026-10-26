FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POKER_DB=/data/poker.sqlite3

RUN groupadd --gid 10001 poker \
    && useradd --uid 10001 --gid poker --no-create-home --shell /usr/sbin/nologin poker \
    && install -d -o poker -g poker -m 0700 /data

WORKDIR /app
COPY --chown=poker:poker mahjong_engine.py game_settings.py fishing.py fishing_gameplay.py fishing_tension.py fishing_power.py server.py voice_transport.py backup.py poker_engine.py arcade_engine.py bonus_engine.py rewards.py result_stats.py online.py realtime.py wallet.py transfers.py social.py club_admin.py member_accounts.py club_features.py view_cache.py clubhouse.py manage_admin.py ./
COPY --chown=poker:poker static/ ./static/

USER poker:poker
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8765/api/bootstrap',timeout=3); assert json.load(r)['capacity']==6"
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8765"]
