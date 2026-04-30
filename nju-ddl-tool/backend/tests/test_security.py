from app.security import create_token, decrypt_json, encrypt_json, hash_password, hash_token, verify_password


class TestHashPassword:
    def test_round_trip(self):
        h = hash_password("mypassword")
        assert verify_password("mypassword", h)

    def test_wrong_password(self):
        h = hash_password("correct")
        assert not verify_password("wrong", h)

    def test_empty_wrong(self):
        h = hash_password("real")
        assert not verify_password("", h)

    def test_tampered_hash(self):
        assert not verify_password("x", "not-a-valid-hash-format")

    def test_none_hash(self):
        assert not verify_password("x", "")
        assert not verify_password("x", "pbkdf2_sha256$1$abc$def")


class TestEncryptJson:
    def test_round_trip(self):
        data = {"key": "value", "num": 42}
        encrypted = encrypt_json(data)
        assert decrypt_json(encrypted) == data

    def test_empty_dict(self):
        assert decrypt_json(encrypt_json({})) == {}

    def test_chinese_text(self):
        data = {"name": "周枫宜", "school": "南京大学"}
        assert decrypt_json(encrypt_json(data)) == data

    def test_different_calls_different_output(self):
        assert encrypt_json({"a": 1}) != encrypt_json({"a": 1})


class TestToken:
    def test_hash_deterministic(self):
        assert hash_token("abc") == hash_token("abc")

    def test_hash_different(self):
        assert hash_token("abc") != hash_token("def")

    def test_create_token_length(self):
        token = create_token()
        assert len(token) >= 32
