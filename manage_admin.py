"""Owner-only CLI bootstrap. Password enters through stdin, never a process argument."""
import argparse
import json
import re
import secrets
import sys
import time
import server
import wallet


def main():
    parser=argparse.ArgumentParser(description='Create a separate club administrator. Existing accounts are never overwritten.')
    parser.add_argument('action',choices=['create'])
    parser.add_argument('--username',required=True)
    parser.add_argument('--nickname',default='牌室管理員')
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_]{3,24}',args.username):parser.error('Invalid username')
    if not 1<=len(args.nickname.strip())<=16:parser.error('Invalid nickname')
    password=sys.stdin.readline().rstrip('\r\n')
    if not 12<=len(password)<=128:parser.error('Supply a 12–128 character initial password through stdin')
    server.initialize()
    with server.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM users WHERE username=?',(args.username,)).fetchone():
            raise SystemExit('Account already exists; no account or password was changed.')
        salt=secrets.token_hex(16)
        uid=db.execute('INSERT INTO users(username,nickname,salt,password_hash,created_at) VALUES(?,?,?,?,?)',
          (args.username,args.nickname.strip(),salt,server.pass_hash(password,salt),server.now())).lastrowid
        wallet.create(db,uid,time.time())
        db.execute('INSERT INTO club_admins VALUES(?,1,?)',(uid,time.time()))
    print(json.dumps({'created':True,'username':args.username,'password_change_required':True}))


if __name__=='__main__':main()
