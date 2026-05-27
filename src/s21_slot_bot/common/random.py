import random
import string

alphabet = string.ascii_letters + string.digits


def random_id(length: int = 8) -> str:
    return "".join(random.choices(alphabet, k=length))
