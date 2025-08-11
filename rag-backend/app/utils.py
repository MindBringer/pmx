import hashlib
def sha1_bytes(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()
