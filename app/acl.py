"""24-bit access-control flags (Community permission model)."""
from __future__ import annotations

ACL_BITS = {
    "read": 1,
    "preview": 2,
    "write": 4,
    "add": 8,
    "rename": 16,
    "delete": 32,
    "immutable": 64,
    "security": 128,
    "import": 256,
    "export": 512,
    "sign": 1024,
    "archive": 2048,
    "workflow": 4096,
    "download": 8192,
    "calendar": 16384,
    "subscription": 32768,
    "password": 65536,
    "move": 131072,
    "email": 262144,
    "automation": 524288,
    "store": 1048576,
    "readingreq": 2097152,
    "print": 4194304,
    "customid": 8388608,
    "revision": 16777216,
}

LEGACY = {
    "read": "can_read",
    "write": "can_write",
    "delete": "can_delete",
    "manage": "can_manage",
}

# Compatibility: "manage" is SECURITY; "read" also covers preview/download.
ALIASES = {
    "manage": "security",
    "read": "read",
}


def bits_from_flags(flags: dict) -> int:
    bits = 0
    for name, on in (flags or {}).items():
        if on and name in ACL_BITS:
            bits |= ACL_BITS[name]
    return bits


def flags_from_bits(bits: int, perm=None) -> dict:
    bits = int(bits or 0)
    if bits == 0 and perm is not None:
        bits = legacy_bits(perm)
    return {name: bool(bits & mask) for name, mask in ACL_BITS.items()}


def legacy_bits(perm) -> int:
    bits = 0
    if getattr(perm, "can_read", False):
        bits |= ACL_BITS["read"] | ACL_BITS["preview"] | ACL_BITS["download"] | ACL_BITS["print"]
    if getattr(perm, "can_write", False):
        bits |= ACL_BITS["write"] | ACL_BITS["add"] | ACL_BITS["rename"] | ACL_BITS["move"] | ACL_BITS["email"]
    if getattr(perm, "can_delete", False):
        bits |= ACL_BITS["delete"]
    if getattr(perm, "can_manage", False):
        bits |= ACL_BITS["security"] | ACL_BITS["immutable"] | ACL_BITS["password"] | ACL_BITS["subscription"]
        bits |= ACL_BITS["workflow"] | ACL_BITS["calendar"] | ACL_BITS["archive"] | ACL_BITS["import"] | ACL_BITS["export"]
    return bits


def has_bit(perm, action: str) -> bool:
    key = ALIASES.get(action, action)
    mask = ACL_BITS.get(key) or ACL_BITS.get(action)
    bits = int(getattr(perm, "bits", 0) or 0)
    if bits:
        if mask and bits & mask:
            return True
        if action == "read" and bits & (ACL_BITS["read"] | ACL_BITS["preview"] | ACL_BITS["download"]):
            return True
        return False
    col = LEGACY.get(action)
    if col:
        return bool(getattr(perm, col, False))
    if action in ("preview", "download", "print") and getattr(perm, "can_read", False):
        return True
    if action in ("add", "rename", "move", "email") and getattr(perm, "can_write", False):
        return True
    if action == "security" and getattr(perm, "can_manage", False):
        return True
    return False


def apply_flags(perm, flags: dict) -> None:
    bits = bits_from_flags(flags)
    perm.bits = bits
    perm.can_read = bool(bits & ACL_BITS["read"])
    perm.can_write = bool(bits & ACL_BITS["write"])
    perm.can_delete = bool(bits & ACL_BITS["delete"])
    perm.can_manage = bool(bits & ACL_BITS["security"])
