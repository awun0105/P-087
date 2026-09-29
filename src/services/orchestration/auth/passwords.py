"""Băm mật khẩu bằng scrypt của thư viện chuẩn (không thêm dependency).

Định dạng: `scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>`; so sánh hằng thời gian.
"""

import base64
import hashlib
import hmac
import secrets

_N, _R, _P, _LEN = 2**14, 8, 1, 32
MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    """Băm mật khẩu với salt ngẫu nhiên 16 byte."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Mật khẩu cần ít nhất {MIN_PASSWORD_LENGTH} ký tự")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_LEN)
    encode = base64.b64encode
    return f"scrypt${_N}${_R}${_P}${encode(salt).decode()}${encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    """Đúng mật khẩu → True; định dạng lạ hoặc sai → False (không ném lỗi ra ngoài)."""
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        observed = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except ValueError:
        return False
    return hmac.compare_digest(observed, expected)


def token_digest(token: str) -> str:
    """Băm token phiên/mã mời trước khi lưu DB (lộ DB không lộ token dùng được)."""
    return hashlib.sha256(token.encode()).hexdigest()
