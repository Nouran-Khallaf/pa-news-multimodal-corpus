from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from normalise import normalise
from corpus_utils import sha256_text

def test_normalisation_is_deterministic():
    source=' A  test\r\n\r\ncontact@example.org '
    a=normalise(source); b=normalise(source)
    assert a==b=='A test\n\n[EMAIL_REDACTED]'
    assert sha256_text(a)==sha256_text(b)
