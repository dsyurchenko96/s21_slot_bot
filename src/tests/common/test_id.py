import string

import pytest

from s21_slot_bot.common.id import hash_id, random_id


class TestId:
    @pytest.mark.parametrize("length", [1, 8, 32])
    def test_random_id_has_requested_length_and_allowed_characters(self, length: int) -> None:
        value = random_id(length)

        assert len(value) == length
        assert set(value) <= set(string.ascii_letters + string.digits)

    def test_hash_id_is_deterministic(self) -> None:
        assert hash_id("same input") == hash_id("same input")

    def test_hash_id_changes_for_different_input(self) -> None:
        assert hash_id("first") != hash_id("second")

    @pytest.mark.parametrize("length", [1, 8, 32])
    def test_hash_id_length_matches_shake_hex_digest_semantics(self, length: int) -> None:
        # hashlib.shake_256(...).hexdigest(n) produces 2*n hex characters.
        assert len(hash_id("hello", length=length)) == length * 2
