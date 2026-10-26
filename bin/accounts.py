#!/usr/bin/env python3
"""Private account labels, fixed priority, and expiring account preferences."""
import argparse
import json
from pathlib import Path
import re
import sys
import tempfile
import time
import math
from datetime import datetime

import os
# The account list holds labels only, never credentials. CLAUDE_LAB_ACCOUNTS moves it.
REGISTRY = Path(os.environ.get('CLAUDE_LAB_ACCOUNTS') or Path(os.environ.get('CLAUDE_LAB_STATE_DIR') or Path.home() / '.local/state/claude-lab') / 'accounts.json')
ORDER=['primary','secondary','token','token-last']
REFERENCES={'saved_native_login':None,'primary_keychain_token':'primary-token',
            'secondary_keychain_token':'secondary-token','existing_lab_keychain_token':'lab',
            'last_backup_keychain_token':'backup-last'}
ALLOWED={'primary':{'saved_native_login','primary_keychain_token'},'secondary':{'secondary_keychain_token'},
         'token':{'existing_lab_keychain_token'},'token-last':{'last_backup_keychain_token'}}


def defaults():
    return {'schema':2,'auto_return':True,'retry_delay_seconds':300,'priority':['primary','token'],
        'temporary':None,'availability':{},'accounts':{
        'primary':{'label':'main','owner':'me','credential':'saved_native_login'},
        'token':{'label':'backup','owner':'unspecified','credential':'existing_lab_keychain_token'}}}


def epoch(value):
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo and math.isfinite(parsed.timestamp()):return parsed.timestamp()
    except (ValueError,TypeError,AttributeError,OverflowError):pass
    raise ValueError('Use an ISO reset timestamp including a timezone')


def validate(data):
    if isinstance(data,dict) and data.get('schema')==1:
        data={**data,'schema':2,'priority':['primary','token'],'temporary':None,'availability':{}}
    if (not isinstance(data,dict) or set(data)!={'schema','auto_return','retry_delay_seconds','accounts','priority','temporary','availability'}
            or data['schema']!=2 or type(data['auto_return']) is not bool
            or type(data['retry_delay_seconds']) is not int or not 60<=data['retry_delay_seconds']<=3600
            or not isinstance(data['accounts'],dict) or not {'primary','token'}<=set(data['accounts'])<=set(ORDER)
            or data['priority']!=[s for s in ORDER if s in data['accounts']]
            or not isinstance(data['availability'],dict) or not set(data['availability'])<=set(data['accounts'])):
        raise ValueError('Invalid account metadata; credentials must remain in the token store')
    for source,account in data['accounts'].items():
        if (not isinstance(account,dict) or set(account)!={'label','owner','credential'}
                or account['credential'] not in ALLOWED[source]):
            raise ValueError('Account credential references cannot be changed here')
        for key in ['label','owner']:
            value=account[key]
            if (not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._@-]{0,63}',value)
                    or re.search(r'(?i)sk-|bearer|token[=:]',value)):
                raise ValueError('Use a short display name; do not enter credentials')
    if len({a['label'].casefold() for a in data['accounts'].values()})!=len(data['accounts']):
        raise ValueError('Account labels must be different')
    for reset in data['availability'].values():
        if type(reset) not in {int,float} or not math.isfinite(reset):raise ValueError('Invalid availability timestamp')
    temporary=data['temporary']
    if temporary is not None:
        if (not isinstance(temporary,dict) or set(temporary)!={'source','until'}
                or temporary['source'] not in data['accounts']):raise ValueError('Invalid temporary selection')
        epoch(temporary['until'])
    return data


def save(data,path=REGISTRY):
    data=validate(data);path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,prefix='.accounts-',delete=False) as output:
        temp=Path(output.name)
        json.dump(data,output,indent=2);output.write('\n')
    temp.chmod(0o600);temp.replace(path)


def load(path=REGISTRY):
    path=Path(path)
    return validate(json.loads(path.read_text())) if path.exists() else defaults()


def ensure(path=REGISTRY):
    if not Path(path).exists():save(defaults(),path)
    return load(path)


def initial_source(data,now=None):
    now=time.time() if now is None else now
    priority=list(data.get('priority',['primary','token']));temporary=data.get('temporary')
    if temporary and epoch(temporary['until'])>now:
        priority=[temporary['source']]+[s for s in priority if s!=temporary['source']]
    return next((s for s in priority if data.get('availability',{}).get(s,0)<=now),priority[0])


def keychain_account(data,source):
    if source not in data['accounts']:raise ValueError('Account is not configured')
    return REFERENCES[data['accounts'][source]['credential']]


def use_owned(data):
    data=validate(data)
    data['accounts']['primary']['credential']='primary_keychain_token'
    data['accounts'].setdefault('secondary',{'label':'main-secondary','owner':'me','credential':'secondary_keychain_token'})
    data['accounts'].setdefault('token-last',{'label':'backup-last','owner':'unspecified','credential':'last_backup_keychain_token'})
    data['priority']=[s for s in ORDER if s in data['accounts']]
    return validate(data)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('list',help='Show metadata only; never reads a credential')
    commands.add_parser('use-owned',help='Select the two additional owned-account tokens in the token store; retain prior backups')
    commands.add_parser('clear-temporary',help='Restore the usual account priority')
    for name in ['label','owner']:
        command=commands.add_parser(name,help='Update display metadata for the next launch')
        command.add_argument('account',choices=ORDER);command.add_argument('value')
    command=commands.add_parser('temporary',help='Prefer one configured account until a reset timestamp')
    command.add_argument('account',choices=ORDER);command.add_argument('--until',required=True)
    command=commands.add_parser('auto-return',help='Apply on the next Claude launch')
    command.add_argument('value',choices=['on','off'])
    opt=parser.parse_args();data=load()
    if opt.command in {'label','owner'}:
        data['accounts'][opt.account][opt.command]=opt.value;save(data)
    elif opt.command=='use-owned':data=use_owned(data);save(data)
    elif opt.command=='temporary':data['temporary']={'source':opt.account,'until':opt.until};save(data)
    elif opt.command=='clear-temporary':data['temporary']=None;save(data)
    elif opt.command=='auto-return':
        data['auto_return']=opt.value=='on';save(data)
    print(json.dumps(data,indent=2))


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError):
        print('Account metadata could not be read or updated. No credential was printed.',file=sys.stderr)
        raise SystemExit(1)
