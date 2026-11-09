"""Offline, machine-bound licenses verified using the owner's public key."""
from __future__ import annotations
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# 冻结：已签发的激活码签在这串字节上，改名会导致存量授权全部失效。
DOMAIN = b'DFMapViewer license v1\0'
PRODUCT = 'DFMapViewer'


class ActivationError(ValueError):
    pass


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')


def unb64(text: str) -> bytes:
    if not re.fullmatch(r'[A-Za-z0-9_-]+', text):
        raise ActivationError('激活码格式不正确，请完整复制。')
    try:
        return base64.b64decode(text + '=' * (-len(text) % 4), altchars=b'-_', validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ActivationError('激活码格式不正确，请完整复制。') from exc


def machine_code(identity: str | None = None) -> str:
    if identity is None:
        if sys.platform != 'win32':
            raise ActivationError('机器码目前仅支持 Windows。')
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                identity = winreg.QueryValueEx(key, 'MachineGuid')[0]
        except OSError as exc:
            raise ActivationError('无法读取 Windows 设备标识，请检查系统权限后重试。') from exc
    try:
        identity = str(uuid.UUID(str(identity).strip()))
    except (ValueError, AttributeError) as exc:
        raise ActivationError('Windows 设备标识无效，无法生成机器码。') from exc
    digest = hashlib.sha256(b'DFMapViewer machine v1\0' + identity.encode('ascii')).digest()[:20]
    body = base64.b32encode(digest).decode('ascii')
    checksum = hashlib.sha256(('DFM1:' + body).encode('ascii')).hexdigest()[:4].upper()
    return 'DFM1-' + '-'.join(body[i:i+8] for i in range(0, 32, 8)) + '-' + checksum


def normalize_machine(text: str) -> str:
    compact = re.sub(r'[\s-]+', '', str(text).upper())
    if not re.fullmatch(r'DFM1[A-Z2-7]{32}[0-9A-F]{4}', compact):
        raise ActivationError('机器码格式不正确，请从软件完整复制。')
    body, checksum = compact[4:36], compact[36:]
    if hashlib.sha256(('DFM1:' + body).encode('ascii')).hexdigest()[:4].upper() != checksum:
        raise ActivationError('机器码校验失败，请重新复制。')
    return 'DFM1-' + '-'.join(body[i:i+8] for i in range(0, 32, 8)) + '-' + checksum


def canonical(claims: dict) -> bytes:
    return json.dumps(claims, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def verify(token: str, machine: str, public_key: bytes) -> dict:
    token = re.sub(r'\s+', '', str(token))
    if len(token) > 4096:
        raise ActivationError('激活码过长，请检查是否复制了其他内容。')
    parts = token.split('.')
    if len(parts) != 3 or parts[0] != 'DFMA1':
        raise ActivationError('激活码格式不正确，请完整复制。')
    payload, signature = unb64(parts[1]), unb64(parts[2])
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, DOMAIN + payload)
    except (InvalidSignature, ValueError) as exc:
        raise ActivationError('激活码校验失败，请检查是否复制完整，或联系软件提供者。') from exc
    try:
        claims = json.loads(payload)
        valid = (isinstance(claims, dict) and set(claims) == {'v', 'product', 'machine', 'issued_at'}
                 and type(claims['v']) is int and claims['v'] == 1 and claims['product'] == PRODUCT
                 and type(claims['issued_at']) is int and claims['issued_at'] >= 0
                 and canonical(claims) == payload)
    except (ValueError, UnicodeError, TypeError):
        valid = False
    if not valid:
        raise ActivationError('激活码内容无效或版本不兼容。')
    if claims['machine'] != normalize_machine(machine):
        raise ActivationError('此激活码不属于本机，请使用当前机器码重新生成。')
    return claims


def public_config() -> dict:
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    try:
        data = json.loads((root / 'assets' / 'activation-public.json').read_text(encoding='utf-8'))
        if data['algorithm'] != 'Ed25519' or len(unb64(data['public_key'])) != 32:
            raise ValueError('invalid public key')
        if not data['issuer_url'].startswith('https://'):
            raise ValueError('invalid issuer URL')
        return data
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise ActivationError('程序缺少有效的激活公钥配置，请重新解压完整软件包。') from exc


def license_path() -> Path:
    from core import exporter
    current = Path(exporter.app_dir()) / 'activation.json'
    # 旧版本把激活记录放在 DFMapViewer 目录，升级后继续沿用已有授权。
    legacy = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'DFMapViewer' / 'activation.json'
    if not current.exists() and legacy.exists():
        return legacy
    return current


def saved_license(machine: str, public_key: bytes, path: Path | None = None) -> tuple[bool, str]:
    path = Path(path or license_path())
    try:
        if not path.exists():
            return False, ''
        if path.stat().st_size > 8192:
            raise ActivationError('本机激活记录无效，请重新输入激活码。')
        token = json.loads(path.read_text(encoding='utf-8'))['token']
        verify(token, machine, public_key)
        return True, ''
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return False, str(exc) if isinstance(exc, ActivationError) else '本机激活记录损坏或无法读取，请重新激活。'


def save_license(token: str, machine: str, public_key: bytes, path: Path | None = None) -> None:
    verify(token, machine, public_key)
    path = Path(path or license_path());path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump({'schema': 1, 'token': re.sub(r'\s+', '', token)}, stream)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
