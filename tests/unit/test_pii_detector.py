from memnex.config import MemnexConfig
from memnex.memory.models import Fact
from memnex.privacy.masker import PIIMasker
from memnex.privacy.pii_detector import PIIDetector


def test_detects_aadhaar_and_pan():
    det = PIIDetector(["aadhaar", "pan"])
    hits = det.detect("Aadhaar 1234 5678 9012, PAN ABCDE1234F here")
    fields = {h.field for h in hits}
    assert "aadhaar" in fields
    assert "pan" in fields


def test_detects_email_and_phone():
    det = PIIDetector(["email", "phone"])
    hits = det.detect("Reach me at vikram@example.com or +91 92410 63955")
    fields = {h.field for h in hits}
    assert "email" in fields
    assert "phone" in fields


def test_masker_hashes_pii():
    cfg = MemnexConfig(tenant_id="t", pii_detection=True, pii_mask_strategy="hash")
    masker = PIIMasker(cfg)
    fact = Fact(fact="Contact vikram@example.com about order 4521")
    masked = masker.mask_fact(fact)
    assert "vikram@example.com" not in masked.fact
    assert "[EMAIL:" in masked.fact


def test_masker_redact_strategy():
    cfg = MemnexConfig(tenant_id="t", pii_detection=True, pii_mask_strategy="redact")
    masker = PIIMasker(cfg)
    fact = Fact(fact="PAN ABCDE1234F")
    masked = masker.mask_fact(fact)
    assert "ABCDE1234F" not in masked.fact
    assert "[PAN]" in masked.fact


def test_masker_noop_when_detection_disabled():
    cfg = MemnexConfig(tenant_id="t", pii_detection=False)
    masker = PIIMasker(cfg)
    fact = Fact(fact="PAN ABCDE1234F")
    masked = masker.mask_fact(fact)
    assert masked.fact == fact.fact
