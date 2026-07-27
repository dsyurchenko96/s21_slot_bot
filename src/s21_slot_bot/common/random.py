import hashlib
import random
import string

alphabet = string.ascii_letters + string.digits


def random_id(length: int = 8) -> str:
    return "".join(random.choices(alphabet, k=length))


def hash_id(hashing_text: str, length: int = 8) -> str:
    return hashlib.shake_256(hashing_text.encode()).hexdigest(length)
