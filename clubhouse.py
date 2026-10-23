"""Offline clubhouse income and public, cash-flow-aware wealth history.

All mutations use the caller's transaction; reads never initialize or award points.
"""
import json
import hashlib
import time
from poker_engine import RuleError

RATE = 60
CAP_HOURS = 24
SECONDS_PER_POINT = 60
CAP = RATE * CAP_HOURS
UNIT = 3_600_000  # Exact point units: hourly rate times elapsed milliseconds.
RATES = (60,90,120,180)
HOURS = (24,30,36,48)
DECOR = ('私人包廂','暖燈小館','尊爵會館','曜金行宮')
SPEED_STEPS = (2,3,4,5)  # Half units: 1x, 1.5x, 2x, 2.5x; additive +50% per decor level.
UPGRADES = {
    'production':dict(name='營運團隊',levels=RATES,costs=(2000,5000,12000)),
    'storage':dict(name='收益金庫',levels=HOURS,costs=(1000,2500,5000)),
    'decor':dict(name='會所裝潢',levels=DECOR,costs=(800,2000,5000))}
MOVES = {'initial', 'buy_in', 'rebuy', 'leave'}


def schema(db,clock=None):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS club_income(user_id INTEGER PRIMARY KEY REFERENCES users(id),last_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS income_claims(user_id INTEGER NOT NULL REFERENCES users(id),operation_id TEXT NOT NULL,
      result TEXT NOT NULL,PRIMARY KEY(user_id,operation_id));
    CREATE TABLE IF NOT EXISTS wealth_accounts(user_id INTEGER PRIMARY KEY REFERENCES users(id),started_at REAL NOT NULL,initial_total INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS wealth_events(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),
      amount INTEGER NOT NULL,game_delta INTEGER NOT NULL,flow_delta INTEGER NOT NULL,kind TEXT NOT NULL,
      event_key TEXT NOT NULL,created_at REAL NOT NULL,UNIQUE(user_id,event_key));
    CREATE INDEX IF NOT EXISTS wealth_events_timeline ON wealth_events(user_id,created_at,id);
    ''')
    columns={r[1] for r in db.execute('PRAGMA table_info(club_income)')}
    for name in ('stored_units','production_level','storage_level','decor_level','revision'):
        if name not in columns:db.execute('ALTER TABLE club_income ADD COLUMN '+name+' INTEGER NOT NULL DEFAULT 0')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS staff_roster(user_id INTEGER NOT NULL REFERENCES users(id),employee_key TEXT NOT NULL,hired_at REAL NOT NULL,PRIMARY KEY(user_id,employee_key));
    CREATE TABLE IF NOT EXISTS staff_jobs(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),employee_key TEXT NOT NULL,
      mission_key TEXT NOT NULL,started_at REAL NOT NULL,finishes_at REAL NOT NULL,reward INTEGER NOT NULL,claimed_at REAL);
    CREATE UNIQUE INDEX IF NOT EXISTS staff_one_active_job ON staff_jobs(user_id,employee_key) WHERE claimed_at IS NULL;
    CREATE INDEX IF NOT EXISTS staff_recent_jobs ON staff_jobs(user_id,id DESC);
    CREATE TABLE IF NOT EXISTS staff_operations(user_id INTEGER NOT NULL REFERENCES users(id),operation_id TEXT NOT NULL,
      fingerprint TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(user_id,operation_id));
    ''')
    db.execute('''CREATE TABLE IF NOT EXISTS income_upgrades(user_id INTEGER NOT NULL REFERENCES users(id),
      operation_id TEXT NOT NULL,fingerprint TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(user_id,operation_id))''')
    if not db.execute("SELECT 1 FROM wallet_meta WHERE key='income_rules_v2'").fetchone():
        clock=time.time() if clock is None else clock
        # Freeze legacy accrual at 50/hour with its original 24h cap, then start
        # the new rate. Reinitialization must never reprice elapsed time.
        for row in db.execute('SELECT user_id,last_at FROM club_income').fetchall():
            elapsed=max(0,int(clock*1000)-int(row['last_at']*1000))
            units=min(1200*UNIT,elapsed*50)
            db.execute('UPDATE club_income SET stored_units=?,last_at=?,revision=revision+1 WHERE user_id=?',
                       (units,max(int(row['last_at']*1000),int(clock*1000))/1000,row['user_id']))
        db.execute("INSERT INTO wallet_meta VALUES('income_rules_v2','60-per-hour')")
    if not db.execute("SELECT 1 FROM wallet_meta WHERE key='clubhouse_speed_v1'").fetchone():
        clock=time.time() if clock is None else clock
        # Settle every existing account at the old rate before enabling its bonus.
        # Completed tasks remain completed; only unfinished work speeds up.
        for row in db.execute('SELECT * FROM club_income').fetchall():
            rate=RATES[row['production_level']];hours=HOURS[row['storage_level']]
            elapsed=max(0,int(clock*1000)-int(row['last_at']*1000))
            units=min(rate*hours*UNIT,row['stored_units']+elapsed*rate)
            anchor=max(int(row['last_at']*1000),int(clock*1000))/1000
            db.execute('UPDATE club_income SET stored_units=?,last_at=?,revision=revision+1 WHERE user_id=?',(units,anchor,row['user_id']))
            accelerate_jobs(db,row['user_id'],anchor,2,SPEED_STEPS[row['decor_level']])
        db.execute("INSERT INTO wallet_meta VALUES('clubhouse_speed_v1','additive-half-per-decor')")


def accelerate_jobs(db,uid,clock,old_step,new_step):
    if old_step==new_step:return
    for job in db.execute('SELECT id,started_at,finishes_at FROM staff_jobs WHERE user_id=? AND claimed_at IS NULL AND finishes_at>?',(uid,clock)).fetchall():
        anchor=max(int(clock*1000),int(job['started_at']*1000))
        remaining=max(0,int(round(job['finishes_at']*1000))-anchor)
        # Round upwards to a millisecond; upgrades never complete work early by rounding.
        finish=(anchor+(remaining*old_step+new_step-1)//new_step)/1000
        db.execute('UPDATE staff_jobs SET finishes_at=? WHERE id=?',(finish,job['id']))


def speed_step(db,uid):
    row=db.execute('SELECT decor_level FROM club_income WHERE user_id=?',(uid,)).fetchone()
    return SPEED_STEPS[row[0]] if row else 2


def enroll(db,uid,clock,total):
    db.execute('INSERT OR IGNORE INTO club_income(user_id,last_at) VALUES(?,?)',(uid,clock))
    db.execute('INSERT OR IGNORE INTO wealth_accounts VALUES(?,?,?)',(uid,clock,total))


def seed(db,clock):
    import wallet
    totals=wallet.in_play(db)
    for row in db.execute('SELECT user_id,balance FROM wallets').fetchall():
        enroll(db,row['user_id'],clock,row['balance']+totals.get(row['user_id'],0))


def record(db,uid,amount,kind,key,clock,*,game=False):
    if not amount or kind in MOVES:return
    db.execute('INSERT OR IGNORE INTO wealth_events(user_id,amount,game_delta,flow_delta,kind,event_key,created_at) VALUES(?,?,?,?,?,?,?)',
               (uid,amount,amount if game else 0,0 if game else amount,kind,key,clock))


def income_state(db,uid,clock,row=None):
    row=row if row is not None else db.execute('SELECT * FROM club_income WHERE user_id=?',(uid,)).fetchone()
    if not row:raise RuleError('會所尚未啟用，請重新登入。')
    rate=RATES[row['production_level']]*SPEED_STEPS[row['decor_level']]//2;hours=HOURS[row['storage_level']]
    elapsed=max(0,int(clock*1000)-int(row['last_at']*1000))
    units=min(rate*hours*UNIT,row['stored_units']+elapsed*rate)
    return row,rate,hours,units


def income_view(db,uid,clock):
    # Pending wallet migration has no enrolled income account yet.
    row=db.execute('SELECT * FROM club_income WHERE user_id=?',(uid,)).fetchone()
    if not row:
        return dict(rate=RATE,cap_hours=CAP_HOURS,cap=CAP,available=0,last_at=clock,
                    seconds_per_point=60,stored_units=0,units_per_point=UNIT,full=False,upgrades=[])
    row,rate,hours,units=income_state(db,uid,clock,row)
    upgrades=[]
    for key,spec in UPGRADES.items():
        level=row[key+'_level'];next_level=level+1
        current=spec['levels'][level];following=spec['levels'][next_level] if next_level<len(spec['levels']) else None
        if key=='production':
            current=current*SPEED_STEPS[row['decor_level']]//2
            following=following*SPEED_STEPS[row['decor_level']]//2 if following is not None else None
        upgrades.append(dict(track=key,name=spec['name'],level=level,max_level=len(spec['levels'])-1,
                             cost=spec['costs'][level] if next_level<len(spec['levels']) else None,
                             current=current,next=following,
                             speed=SPEED_STEPS[level]/2 if key=='decor' else None,
                             next_speed=SPEED_STEPS[next_level]/2 if key=='decor' and next_level<len(SPEED_STEPS) else None))
    return dict(rate=rate,cap_hours=hours,cap=rate*hours,available=units//UNIT,
                last_at=row['last_at'],stored_units=row['stored_units'],units_per_point=UNIT,
                seconds_per_point=3600/rate,full=units>=rate*hours*UNIT,
                revision=row['revision'],decor_level=row['decor_level'],decor_name=DECOR[row['decor_level']],
                base_rate=RATES[row['production_level']],speed_multiplier=SPEED_STEPS[row['decor_level']]/2,upgrades=upgrades)


def claim(db,user,data,clock):
    import wallet,member_accounts
    uid=user['id'];member_accounts.require_active(db,uid)
    if not wallet.active(db):raise RuleError('點數制度尚未啟用。')
    op=member_accounts.operation_id(data.get('operation_id'))
    previous=db.execute('SELECT result FROM income_claims WHERE user_id=? AND operation_id=?',(uid,op)).fetchone()
    if previous:return {**json.loads(previous[0]),'replayed':True}
    row,rate,hours,units=income_state(db,uid,clock);amount=units//UNIT
    if amount:
        wallet.transfer(db,uid,amount,'passive','passive:'+op,clock)
        db.execute('UPDATE club_income SET stored_units=?,last_at=?,revision=revision+1 WHERE user_id=?',
                   (units-amount*UNIT,max(int(row['last_at']*1000),int(clock*1000))/1000,uid))
    result=dict(claimed=bool(amount),amount=amount,replayed=False,
                message=f'已領取會所收益 {amount:,} 點。' if amount else '收益累積中，達到 1 點即可領取。')
    db.execute('INSERT INTO income_claims VALUES(?,?,?)',(uid,op,json.dumps(result,ensure_ascii=False)))
    return result


def upgrade(db,user,data,clock):
    import wallet,member_accounts
    from member_accounts import AccountError
    uid=user['id'];member_accounts.require_active(db,uid)
    if not wallet.active(db):raise RuleError('點數制度尚未啟用。')
    op=member_accounts.operation_id(data.get('operation_id'))
    track=data.get('track');level=data.get('expected_level');revision=data.get('revision')
    if not isinstance(track,str) or track not in UPGRADES or type(level) is not int or type(revision) is not int:raise RuleError('會所升級資料無效。')
    fingerprint=hashlib.sha256(json.dumps([track,level,revision]).encode()).hexdigest()
    old=db.execute('SELECT fingerprint,result FROM income_upgrades WHERE user_id=? AND operation_id=?',(uid,op)).fetchone()
    if old:
        if old['fingerprint']!=fingerprint:raise AccountError('同一編號已用於其他升級。',409,'operation_conflict')
        return {**json.loads(old['result']),'replayed':True}
    row,rate,hours,units=income_state(db,uid,clock);spec=UPGRADES[track]
    if row['revision']!=revision or row[track+'_level']!=level:raise AccountError('會所已在其他分頁更新，請重新確認等級與費用。',409,'stale_clubhouse')
    if level>=len(spec['levels'])-1:raise RuleError('這項設施已達最高等級。')
    cost=spec['costs'][level]
    # Includes ledger, public wealth history, accrued points and receipt in one savepoint.
    db.execute('SAVEPOINT clubhouse_upgrade')
    try:
        wallet.transfer(db,uid,-cost,'club_upgrade','club-upgrade:'+op,clock)
        db.execute('UPDATE club_income SET '+track+'_level='+track+'_level+1,stored_units=?,last_at=?,revision=revision+1 WHERE user_id=?',
                   (units,max(int(row['last_at']*1000),int(clock*1000))/1000,uid))
        if track=='decor':accelerate_jobs(db,uid,max(clock,row['last_at']),SPEED_STEPS[level],SPEED_STEPS[level+1])
        result=dict(ok=True,replayed=False,track=track,level=level+1,cost=cost,message=f"{spec['name']}已升到 Lv.{level+2}，花費 {cost:,} 點。")
        db.execute('INSERT INTO income_upgrades VALUES(?,?,?,?)',(uid,op,fingerprint,json.dumps(result,ensure_ascii=False)))
        db.execute('RELEASE SAVEPOINT clubhouse_upgrade')
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT clubhouse_upgrade');db.execute('RELEASE SAVEPOINT clubhouse_upgrade');raise
    return result


def public_profile(db,uid,clock,period='7d'):
    import member_accounts,rewards,wallet
    from member_accounts import AccountError
    periods={'1d':(86400,3600),'7d':(7*86400,6*3600),'30d':(30*86400,86400)}
    if period not in periods:raise RuleError('請選擇近 24 小時、7 天或 30 天。')
    user=db.execute('SELECT id,username,nickname,created_at FROM users WHERE id=?',(uid,)).fetchone()
    if not user or member_accounts.state(db,uid)['status']!='active':raise AccountError('找不到此成員。',404,'not_found')
    club=db.execute('SELECT decor_level FROM club_income WHERE user_id=?',(uid,)).fetchone()
    person={**dict(user),'clubhouse':dict(level=club[0],name=DECOR[club[0]]) if club else None,**member_accounts.public_profiles(db).get(uid,{}),'cosmetics':rewards.profile_map(db).get(uid,{})}
    anchor=db.execute('SELECT started_at,initial_total FROM wealth_accounts WHERE user_id=?',(uid,)).fetchone()
    total=wallet.view(db,uid,clock)['total']
    span,step=periods[period];start=max(anchor['started_at'] if anchor else clock,clock-span)
    opening=(anchor['initial_total']+db.execute('SELECT COALESCE(sum(amount),0) FROM wealth_events WHERE user_id=? AND created_at<?',(uid,start)).fetchone()[0]) if anchor else total
    points=[dict(at=start,total=opening)];running=opening
    # At most 32 buckets, irrespective of the number of hands; only fetched on demand.
    rows=db.execute('SELECT CAST((created_at-?)/? AS INTEGER) AS bucket,sum(amount) AS amount,sum(game_delta) AS game,sum(flow_delta) AS flow FROM wealth_events WHERE user_id=? AND created_at>=? AND created_at<=? GROUP BY bucket ORDER BY bucket',
                    (start,step,uid,start,clock)).fetchall()
    for row in rows:
        running+=row['amount'];points.append(dict(at=min(clock,start+(row['bucket']+1)*step),total=running))
    if points[-1]['at']!=clock or points[-1]['total']!=total:points.append(dict(at=clock,total=total))
    stats=db.execute('SELECT count(*) AS hands,COALESCE(sum(profit),0) AS profit,COALESCE(sum(profit>0),0) AS wins FROM poker_results WHERE user_id=?',(uid,)).fetchone()
    change=total-opening
    return dict(person=person,stats=dict(stats),wealth=dict(total=total,opening=opening,change=change,
                percent=round(change/opening*100,2) if opening>0 else None,
                game_profit=sum(r['game'] for r in rows),net_flow=sum(r['flow'] for r in rows),
                period=period,started_at=anchor['started_at'] if anchor else clock,from_at=start,to_at=clock,
                bucket_seconds=step,points=points,tracking='since_release'),server_time=clock)


EMPLOYEES = {
    'concierge':dict(name='阿凱',role='值班管家',cost=0,color='amber'),
    'host':dict(name='小霓',role='酒廊接待',cost=1500,color='violet'),
    'steward':dict(name='阿岳',role='場務主管',cost=4000,color='teal')}
MISSIONS = {
    'setup':dict(name='包廂整備',description='檢查牌桌、備齊茶點，迎接今晚的朋友。',seconds=3600,reward=60),
    'hosting':dict(name='酒廊接待',description='照顧來訪會員，完成一輪會所接待。',seconds=14400,reward=300),
    'nightshift':dict(name='夜間營運',description='巡查設施與整理場地，維持會所夜間營運。',seconds=28800,reward=650)}


def staff_view(db,uid,clock):
    step=speed_step(db,uid)
    owned={'concierge'}|{r[0] for r in db.execute('SELECT employee_key FROM staff_roster WHERE user_id=?',(uid,))}
    active={r['employee_key']:dict(r) for r in db.execute('SELECT id,employee_key,mission_key,started_at,finishes_at,reward FROM staff_jobs WHERE user_id=? AND claimed_at IS NULL',(uid,))}
    employees=[]
    for key,spec in EMPLOYEES.items():
        job=active.get(key)
        if job:job.update(name=MISSIONS[job['mission_key']]['name'],ready=clock>=job['finishes_at'])
        employees.append(dict(key=key,**spec,owned=key in owned,job=job))
    history=[dict(r) for r in db.execute('SELECT id,employee_key,mission_key,reward,claimed_at FROM staff_jobs WHERE user_id=? AND claimed_at IS NOT NULL ORDER BY id DESC LIMIT 6',(uid,))]
    missions=[dict(key=key,**{**spec,'seconds':spec['seconds']*2/step},base_seconds=spec['seconds']) for key,spec in MISSIONS.items()]
    return dict(employees=employees,missions=missions,history=history,server_time=clock,speed_multiplier=step/2)


def staff_mutate(db,user,action,data,clock):
    import member_accounts,wallet
    from member_accounts import AccountError
    uid=user['id'];member_accounts.require_active(db,uid)
    if not wallet.active(db):raise RuleError('點數制度尚未啟用。')
    if action not in ('hire','dispatch','collect'):raise RuleError('員工操作無效。')
    op=member_accounts.operation_id(data.get('operation_id'))
    employee=data.get('employee');mission=data.get('mission');job_id=data.get('job_id')
    if action in ('hire','dispatch') and (not isinstance(employee,str) or employee not in EMPLOYEES):raise RuleError('請選擇有效的員工。')
    if action=='dispatch' and (not isinstance(mission,str) or mission not in MISSIONS):raise RuleError('請選擇有效的派遣任務。')
    if action=='collect' and (type(job_id) is not int or not 1<=job_id<2**63):raise RuleError('任務編號無效。')
    fingerprint=hashlib.sha256(json.dumps([action,employee if action!='collect' else job_id,mission if action=='dispatch' else None]).encode()).hexdigest()
    old=db.execute('SELECT fingerprint,result FROM staff_operations WHERE user_id=? AND operation_id=?',(uid,op)).fetchone()
    if old:
        if old['fingerprint']!=fingerprint:raise AccountError('同一編號已用於其他員工操作。',409,'operation_conflict')
        return {**json.loads(old['result']),'replayed':True}
    owned=employee=='concierge' or bool(db.execute('SELECT 1 FROM staff_roster WHERE user_id=? AND employee_key=?',(uid,employee)).fetchone())
    db.execute('SAVEPOINT staff_action')
    try:
        if action=='hire':
            if not owned:
                wallet.transfer(db,uid,-EMPLOYEES[employee]['cost'],'staff_hire','staff-hire:'+op,clock)
                db.execute('INSERT INTO staff_roster VALUES(?,?,?)',(uid,employee,clock))
            result=dict(ok=True,hired=not owned,message='這位員工已在團隊中。' if owned else EMPLOYEES[employee]['name']+'已加入團隊，可立即派遣。')
        elif action=='dispatch':
            if not owned:raise RuleError('請先招募這位員工。')
            if db.execute('SELECT 1 FROM staff_jobs WHERE user_id=? AND employee_key=? AND claimed_at IS NULL',(uid,employee)).fetchone():raise AccountError('這位員工仍有任務，請先完成並領取獎勵。',409,'employee_busy')
            spec=MISSIONS[mission]
            duration=spec['seconds']*2/speed_step(db,uid)
            ident=db.execute('INSERT INTO staff_jobs(user_id,employee_key,mission_key,started_at,finishes_at,reward) VALUES(?,?,?,?,?,?)',(uid,employee,mission,clock,clock+duration,spec['reward'])).lastrowid
            result=dict(ok=True,job_id=ident,message=EMPLOYEES[employee]['name']+'已出發執行'+spec['name']+'，離線也會繼續。')
        else:
            job=db.execute('SELECT * FROM staff_jobs WHERE id=? AND user_id=?',(job_id,uid)).fetchone()
            if not job:raise AccountError('找不到這個派遣任務。',404,'not_found')
            if job['claimed_at'] is not None:result=dict(ok=True,collected=False,amount=0,message='這趟派遣獎勵已領取，不會重複入帳。')
            else:
                if clock<job['finishes_at']:raise RuleError('派遣尚未完成，請等倒數結束後再領取。')
                wallet.transfer(db,uid,job['reward'],'staff_mission','staff-job:'+str(job_id),clock)
                db.execute('UPDATE staff_jobs SET claimed_at=? WHERE id=?',(clock,job_id))
                result=dict(ok=True,collected=True,amount=job['reward'],message=f"派遣完成，已領取 {job['reward']:,} 點。")
        result['replayed']=False
        db.execute('INSERT INTO staff_operations VALUES(?,?,?,?)',(uid,op,fingerprint,json.dumps(result,ensure_ascii=False)))
        db.execute('RELEASE SAVEPOINT staff_action')
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT staff_action');db.execute('RELEASE SAVEPOINT staff_action');raise
    return result
