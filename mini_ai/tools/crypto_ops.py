"""
crypto_ops.py – Cryptographic utilities (hashing, HMAC, random generation, UUID).
All stdlib: hashlib, hmac, secrets, uuid, base64. No actual encryption to avoid security liability.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import string
import uuid
from pathlib import Path
from typing import Any


def crypto_op(operation: str, input_text: str = "", key: str = "", algorithm: str = "sha256") -> dict[str, Any]:
    """Cryptographic utilities.

    Operations:
    - hash: hash text or file (algorithm: md5, sha1, sha256, sha512)
    - hash_file: hash a file by path
    - hmac_sign: create HMAC signature (key required)
    - hmac_verify: verify HMAC (input_text='message|signature', key required)
    - random: generate random string (input_text=length, algorithm=type: hex/alpha/alnum/bytes)
    - uuid: generate UUID v4
    - password: generate secure password (input_text=length, default 16)
    - encode: encode text (algorithm: base64/base32/hex)
    - decode: decode text (algorithm: base64/base32/hex)
    - checksum: generate file checksum (input_text=file path)
    """
    operation = operation.lower().strip()

    if operation == "hash":
        return _hash_text(input_text, algorithm)
    elif operation == "hash_file":
        return _hash_file(input_text, algorithm)
    elif operation == "hmac_sign":
        return _hmac_sign(input_text, key, algorithm)
    elif operation == "hmac_verify":
        return _hmac_verify(input_text, key, algorithm)
    elif operation == "random":
        return _random_string(input_text, algorithm)
    elif operation == "uuid":
        return _generate_uuid()
    elif operation == "password":
        return _generate_password(input_text)
    elif operation == "encode":
        return _encode(input_text, algorithm)
    elif operation == "decode":
        return _decode(input_text, algorithm)
    elif operation == "checksum":
        return _hash_file(input_text, algorithm)
    else:
        return {"success": False, "error": f"Unknown operation: '{operation}'. Available: hash, hash_file, hmac_sign, hmac_verify, random, uuid, password, encode, decode, checksum"}


def _hash_text(text: str, algorithm: str) -> dict[str, Any]:
    """Hash a text string."""
    if not text:
        return {"success": False, "error": "Input text required"}

    algo = algorithm.lower().strip()
    algos = {"md5": hashlib.md5, "sha1": hashlib.sha1, "sha256": hashlib.sha256, "sha512": hashlib.sha512}

    if algo not in algos:
        return {"success": False, "error": f"Unknown algorithm: '{algo}'. Available: md5, sha1, sha256, sha512"}

    digest = algos[algo](text.encode("utf-8")).hexdigest()
    return {"success": True, "result": f"{algo}: {digest}"}


def _hash_file(file_path: str, algorithm: str) -> dict[str, Any]:
    """Hash a file."""
    if not file_path:
        return {"success": False, "error": "File path required"}

    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}
    if not path.is_file():
        return {"success": False, "error": f"Not a file: {file_path}"}

    algo = algorithm.lower().strip()
    algos = {"md5": hashlib.md5, "sha1": hashlib.sha1, "sha256": hashlib.sha256, "sha512": hashlib.sha512}

    if algo not in algos:
        return {"success": False, "error": f"Unknown algorithm: '{algo}'. Available: md5, sha1, sha256, sha512"}

    try:
        h = algos[algo]()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        digest = h.hexdigest()
        size = path.stat().st_size
        return {"success": True, "result": f"File: {path.name}\nSize: {size} bytes\n{algo}: {digest}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _hmac_sign(message: str, key: str, algorithm: str) -> dict[str, Any]:
    """Create HMAC signature."""
    if not message:
        return {"success": False, "error": "Message required"}
    if not key:
        return {"success": False, "error": "Key required for HMAC signing"}

    algo = algorithm.lower().strip()
    algo_map = {"md5": "md5", "sha1": "sha1", "sha256": "sha256", "sha512": "sha512"}
    if algo not in algo_map:
        algo = "sha256"

    signature = hmac.new(key.encode(), message.encode(), algo).hexdigest()
    return {"success": True, "result": f"HMAC-{algo.upper()}: {signature}"}


def _hmac_verify(input_text: str, key: str, algorithm: str) -> dict[str, Any]:
    """Verify HMAC signature. Input format: 'message|signature'."""
    if "|" not in input_text:
        return {"success": False, "error": "Format: 'message|signature'"}
    if not key:
        return {"success": False, "error": "Key required for HMAC verification"}

    parts = input_text.rsplit("|", 1)
    message, expected_sig = parts[0], parts[1].strip()

    algo = algorithm.lower().strip()
    if algo not in ("md5", "sha1", "sha256", "sha512"):
        algo = "sha256"

    actual_sig = hmac.new(key.encode(), message.encode(), algo).hexdigest()
    valid = hmac.compare_digest(actual_sig, expected_sig)

    if valid:
        return {"success": True, "result": "Signature is VALID ✓"}
    return {"success": True, "result": f"Signature is INVALID ✗\n  Expected: {expected_sig}\n  Got: {actual_sig}"}


def _random_string(length_str: str, type_str: str) -> dict[str, Any]:
    """Generate random string."""
    try:
        length = int(length_str) if length_str.strip() else 32
    except ValueError:
        length = 32

    length = min(length, 1024)  # cap at 1024
    type_str = type_str.lower().strip() if type_str else "hex"

    if type_str == "hex":
        result = secrets.token_hex(length // 2 + 1)[:length]
    elif type_str in ("alpha", "letters"):
        result = "".join(secrets.choice(string.ascii_letters) for _ in range(length))
    elif type_str in ("alnum", "alphanumeric"):
        result = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))
    elif type_str == "bytes":
        result = secrets.token_bytes(length).hex()
    elif type_str == "urlsafe":
        result = secrets.token_urlsafe(length)[:length]
    else:
        result = secrets.token_hex(length // 2 + 1)[:length]

    return {"success": True, "result": f"Random ({type_str}, {length} chars): {result}"}


def _generate_uuid() -> dict[str, Any]:
    """Generate UUID v4."""
    new_uuid = str(uuid.uuid4())
    return {"success": True, "result": f"UUID v4: {new_uuid}"}


def _generate_password(length_str: str) -> dict[str, Any]:
    """Generate a secure password."""
    try:
        length = int(length_str) if length_str.strip() else 16
    except ValueError:
        length = 16

    length = max(8, min(length, 128))

    # Ensure at least one of each type
    chars = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    password = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*()-_=+"),
    ]
    password.extend(secrets.choice(chars) for _ in range(length - 4))
    # Shuffle
    password_list = list(password)
    import random
    random.SystemRandom().shuffle(password_list)
    result = "".join(password_list)

    return {"success": True, "result": f"Password ({length} chars): {result}"}


def _encode(text: str, encoding: str) -> dict[str, Any]:
    """Encode text."""
    if not text:
        return {"success": False, "error": "Input text required"}

    encoding = encoding.lower().strip()
    try:
        if encoding == "base64":
            result = base64.b64encode(text.encode()).decode()
        elif encoding == "base32":
            result = base64.b32encode(text.encode()).decode()
        elif encoding == "hex":
            result = text.encode().hex()
        elif encoding == "urlsafe":
            result = base64.urlsafe_b64encode(text.encode()).decode()
        else:
            return {"success": False, "error": f"Unknown encoding: '{encoding}'. Available: base64, base32, hex, urlsafe"}
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _decode(text: str, encoding: str) -> dict[str, Any]:
    """Decode text."""
    if not text:
        return {"success": False, "error": "Input text required"}

    encoding = encoding.lower().strip()
    try:
        if encoding == "base64":
            result = base64.b64decode(text.encode()).decode("utf-8", errors="replace")
        elif encoding == "base32":
            result = base64.b32decode(text.encode()).decode("utf-8", errors="replace")
        elif encoding == "hex":
            result = bytes.fromhex(text).decode("utf-8", errors="replace")
        elif encoding == "urlsafe":
            result = base64.urlsafe_b64decode(text.encode()).decode("utf-8", errors="replace")
        else:
            return {"success": False, "error": f"Unknown encoding: '{encoding}'. Available: base64, base32, hex, urlsafe"}
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": f"Decode error: {e}"}
