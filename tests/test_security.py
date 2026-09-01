from app.security import compute_signature, verify_webhook_signature

SECRET = "Vithu@1106"


def test_known_good_razorpay_payload_verifies(razorpay_captured_webhook):
    fx = razorpay_captured_webhook
    assert verify_webhook_signature(fx["body"], fx["signature"], SECRET) is True


def test_tampered_body_fails(razorpay_captured_webhook):
    fx = razorpay_captured_webhook
    tampered = fx["body"].replace(b"captured", b"CAPTURED", 1)
    assert verify_webhook_signature(tampered, fx["signature"], SECRET) is False


def test_wrong_secret_fails(razorpay_captured_webhook):
    fx = razorpay_captured_webhook
    assert verify_webhook_signature(fx["body"], fx["signature"], "wrong-secret") is False


def test_missing_signature_fails(razorpay_captured_webhook):
    fx = razorpay_captured_webhook
    assert verify_webhook_signature(fx["body"], None, SECRET) is False
    assert verify_webhook_signature(fx["body"], "", SECRET) is False


def test_compute_is_hex_sha256(razorpay_captured_webhook):
    sig = compute_signature(razorpay_captured_webhook["body"], SECRET)
    assert len(sig) == 64 and all(c in "0123456789abcdef" for c in sig)
