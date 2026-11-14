"""PuTTY private keys (.ppk), read into OpenSSH form.

The migration pages and SFTP destinations take a private key pasted in, and
paramiko reads only OpenSSH/PEM keys; a .ppk from PuTTYgen, the key most
Windows users have, was refused as unreadable (operator, 2026-11-14, cPanel
import). Formats 2 and 3, unencrypted or with a passphrase (format 2:
AES-256-CBC from SHA-1; format 3: Argon2id), for RSA, Ed25519, ECDSA and DSA
keys. The MAC is checked, which is also what tells a wrong passphrase.

Shared by OPanel and BPanel: keep the two copies identical.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed25519, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

HEADER = "PuTTY-User-Key-File-"
_CURVES = {
    "ecdsa-sha2-nistp256": ec.SECP256R1(),
    "ecdsa-sha2-nistp384": ec.SECP384R1(),
    "ecdsa-sha2-nistp521": ec.SECP521R1(),
}


class PpkError(ValueError):
    """A .ppk that cannot be read; the message says why, for the operator."""


def is_ppk(text: str) -> bool:
    return (text or "").lstrip().startswith(HEADER)


def _fields(text: str) -> tuple[int, dict, bytes, bytes]:
    lines = [line.rstrip("\r") for line in text.strip().splitlines()]
    fields: dict[str, str] = {}
    blobs: dict[str, bytes] = {}
    index = 0
    version = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if ":" not in line:
            raise PpkError("This PuTTY key file is damaged (a line without a name)")
        name, _, value = line.partition(":")
        value = value.strip()
        if name.startswith(HEADER):
            version = int(name[len(HEADER):] or 0)
            fields["Algorithm"] = value
            continue
        if name in ("Public-Lines", "Private-Lines"):
            try:
                count = int(value)
            except ValueError:
                raise PpkError("This PuTTY key file is damaged") from None
            chunk = "".join(lines[index:index + count])
            index += count
            try:
                blobs[name] = base64.b64decode(chunk, validate=True)
            except ValueError:
                raise PpkError("This PuTTY key file is damaged (bad base64)") from None
            continue
        fields[name] = value
    if version not in (2, 3):
        raise PpkError(f"PuTTY key format {version or '?'} is not supported; save it again with PuTTYgen 0.75 or newer")
    if "Public-Lines" not in blobs or "Private-Lines" not in blobs or "Private-MAC" not in fields:
        raise PpkError("This PuTTY key file is incomplete; copy the whole .ppk file")
    return version, fields, blobs["Public-Lines"], blobs["Private-Lines"]


def _string(value: bytes) -> bytes:
    return struct.pack(">I", len(value)) + value


class _Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def string(self) -> bytes:
        if self.pos + 4 > len(self.data):
            raise PpkError("This PuTTY key file is damaged (short key data)")
        (size,) = struct.unpack(">I", self.data[self.pos:self.pos + 4])
        start = self.pos + 4
        if start + size > len(self.data):
            raise PpkError("This PuTTY key file is damaged (short key data)")
        self.pos = start + size
        return self.data[start:self.pos]

    def mpint(self) -> int:
        return int.from_bytes(self.string(), "big", signed=True)


def _argon2(fields: dict, passphrase: bytes) -> bytes:
    flavour = fields.get("Key-Derivation", "")
    if flavour != "Argon2id":
        raise PpkError(f"This PuTTY key's passphrase uses {flavour or 'an unknown key derivation'}; "
                       "save it again with PuTTYgen using Argon2id, or export it as an OpenSSH key")
    try:
        from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
    except ImportError:  # pragma: no cover - cryptography < 44
        raise PpkError("This server cannot read a passphrase-protected PuTTY key of format 3; "
                       "export it as an OpenSSH key in PuTTYgen") from None
    try:
        kdf = Argon2id(salt=bytes.fromhex(fields["Argon2-Salt"]), length=80,
                       iterations=int(fields["Argon2-Passes"]), lanes=int(fields["Argon2-Parallelism"]),
                       memory_cost=int(fields["Argon2-Memory"]))
    except (KeyError, ValueError):
        raise PpkError("This PuTTY key file is damaged (its Argon2 settings)") from None
    return kdf.derive(passphrase)


def _decrypt(version: int, fields: dict, private: bytes, passphrase: str) -> tuple[bytes, bytes]:
    """The private blob in the clear, and the key its MAC is made with."""
    encryption = fields.get("Encryption", "none")
    secret = (passphrase or "").encode("utf-8")
    if encryption == "none":
        if version == 2:
            return private, hashlib.sha1(b"putty-private-key-file-mac-key").digest()
        return private, b""
    if encryption != "aes256-cbc":
        raise PpkError(f"PuTTY key encryption {encryption} is not supported")
    if not secret:
        raise PpkError("This PuTTY key has a passphrase: enter it in the passphrase field")
    if len(private) % 16:
        raise PpkError("This PuTTY key file is damaged (encrypted data)")
    if version == 2:
        key = (hashlib.sha1(b"\0\0\0\0" + secret).digest() + hashlib.sha1(b"\0\0\0\1" + secret).digest())[:32]
        iv, mac_key = b"\0" * 16, hashlib.sha1(b"putty-private-key-file-mac-key" + secret).digest()
    else:
        derived = _argon2(fields, secret)
        key, iv, mac_key = derived[:32], derived[32:48], derived[48:80]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return decryptor.update(private) + decryptor.finalize(), mac_key


def _check_mac(version: int, fields: dict, public: bytes, private: bytes, mac_key: bytes) -> None:
    signed = b"".join(_string(part) for part in (
        fields["Algorithm"].encode(), fields.get("Encryption", "none").encode(),
        fields.get("Comment", "").encode("utf-8"), public, private))
    digest = hashlib.sha1 if version == 2 else hashlib.sha256
    expected = hmac.new(mac_key, signed, digest).hexdigest()
    if not hmac.compare_digest(expected, fields["Private-MAC"].strip().lower()):
        if fields.get("Encryption", "none") != "none":
            raise PpkError("The passphrase of this PuTTY key is wrong")
        raise PpkError("This PuTTY key file is damaged or was changed (its check does not match)")


def _private_key(algorithm: str, public: bytes, private: bytes):
    pub, priv = _Reader(public), _Reader(private)
    if pub.string().decode("ascii", "replace") != algorithm:
        raise PpkError("This PuTTY key file is damaged (its key type does not match)")
    if algorithm == "ssh-rsa":
        e, n = pub.mpint(), pub.mpint()
        d, p, q = priv.mpint(), priv.mpint(), priv.mpint()
        return rsa.RSAPrivateNumbers(p, q, d, rsa.rsa_crt_dmp1(d, p), rsa.rsa_crt_dmq1(d, q),
                                     rsa.rsa_crt_iqmp(p, q), rsa.RSAPublicNumbers(e, n)).private_key()
    if algorithm == "ssh-ed25519":
        return ed25519.Ed25519PrivateKey.from_private_bytes(priv.string()[-32:])
    if algorithm in _CURVES:
        return ec.derive_private_key(priv.mpint(), _CURVES[algorithm])
    if algorithm == "ssh-dss":
        p, q, g, y = pub.mpint(), pub.mpint(), pub.mpint(), pub.mpint()
        x = priv.mpint()
        return dsa.DSAPrivateNumbers(x, dsa.DSAPublicNumbers(y, dsa.DSAParameterNumbers(p, q, g))).private_key()
    raise PpkError(f"PuTTY keys of type {algorithm} are not supported; use RSA, Ed25519 or ECDSA")


def to_openssh(text: str, passphrase: str = "") -> str:
    """The .ppk ``text`` as an unencrypted OpenSSH private key (PEM text).

    Kept in memory only, like the key it came from."""
    version, fields, public, private = _fields(text)
    clear, mac_key = _decrypt(version, fields, private, passphrase)
    _check_mac(version, fields, public, clear, mac_key)
    key = _private_key(fields["Algorithm"], public, clear)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                             serialization.NoEncryption()).decode("ascii")
