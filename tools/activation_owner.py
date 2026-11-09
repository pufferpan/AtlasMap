"""Owner-only key setup and offline license issuance. Never bundle private keys."""
from pathlib import Path
import argparse
import json
import os
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from core import activation


def load_key(path):
    key=serialization.load_pem_private_key(Path(path).read_bytes(),password=None)
    if not isinstance(key,Ed25519PrivateKey):raise ValueError('需要 Ed25519 签发密钥')
    return key


def issue(key,machine,issued_at=None):
    claims=dict(v=1,product=activation.PRODUCT,machine=activation.normalize_machine(machine),
                issued_at=int(time.time()) if issued_at is None else issued_at)
    payload=activation.canonical(claims)
    return 'DFMA1.'+activation.b64(payload)+'.'+activation.b64(key.sign(activation.DOMAIN+payload))


def initialize(private_file,public_file,url):
    private_file=Path(private_file);public_file=Path(public_file)
    if private_file.exists():key=load_key(private_file)
    else:
        if public_file.exists():raise ValueError('已有公钥却找不到签发密钥，拒绝替换现有激活体系；请恢复原私钥。')
        private_file.parent.mkdir(parents=True,exist_ok=True)
        key=Ed25519PrivateKey.generate()
        data=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        fd=os.open(private_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(data)
        if os.name=='nt':
            import win32api,win32con,win32security,ntsecuritycon
            token=win32security.OpenProcessToken(win32api.GetCurrentProcess(),win32con.TOKEN_QUERY)
            try:sid=win32security.GetTokenInformation(token,win32security.TokenUser)[0]
            finally:token.Close()
            dacl=win32security.ACL();dacl.AddAccessAllowedAce(win32security.ACL_REVISION,ntsecuritycon.FILE_ALL_ACCESS,sid)
            win32security.SetNamedSecurityInfo(str(private_file),win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION|win32security.PROTECTED_DACL_SECURITY_INFORMATION,None,None,dacl,None)
    public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    config=dict(algorithm='Ed25519',public_key=activation.b64(public),issuer_url=url)
    if public_file.exists() and json.loads(public_file.read_text(encoding='utf-8'))['public_key']!=config['public_key']:
        raise ValueError('签发密钥与现有软件公钥不一致，拒绝覆盖。')
    public_file.parent.mkdir(parents=True,exist_ok=True)
    public_file.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    return config


def main():
    parser=argparse.ArgumentParser(description='AtlasMap 管理者签发工具')
    sub=parser.add_subparsers(dest='command',required=True)
    setup=sub.add_parser('init');setup.add_argument('--private-key',required=True);setup.add_argument('--public-config',required=True);setup.add_argument('--url',required=True)
    sign=sub.add_parser('issue');sign.add_argument('--private-key',required=True);sign.add_argument('--machine',required=True);sign.add_argument('--out',required=True)
    args=parser.parse_args()
    if args.command=='init':
        initialize(args.private_key,args.public_config,args.url);print('Owner key ready; public configuration saved.')
    else:
        Path(args.out).write_text(issue(load_key(args.private_key),args.machine)+'\n',encoding='utf-8');print('License saved.')


if __name__=='__main__':main()
