from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from corpus_utils import tokenise, sentence_split, readability, log_likelihood, log_ratio, mattr

def test_text_helpers():
    text='This is one sentence. This is another sentence with more words.'
    assert len(sentence_split(text))==2
    assert tokenise("Nation's values") == ["nation's",'values']
    assert readability(text)['word_count']>5
    assert 0 < mattr(tokenise(text)) <= 1

def test_keyness_helpers():
    assert log_likelihood(20,100,5,100)>0
    assert log_ratio(20,100,5,100)>0
