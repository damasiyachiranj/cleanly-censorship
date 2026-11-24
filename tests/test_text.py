import json

import pytest

from cleanly.matcher import Matcher, normalize, tokenize
from cleanly.text import apply_effect, censor_file_text, censor_string, mask
from cleanly.wordlist import Entry, UserList, build_list, load_standard


@pytest.fixture(scope="module")
def standard():
    return load_standard("en")


def m(standard, mode="standard", strictness="strict", user=None):
    return Matcher(build_list(standard, mode, strictness, user))


# --- list building -------------------------------------------------------

def test_strictness_filters(standard):
    light = build_list(standard, strictness="light")
    assert {e.severity for e in light} == {"slur"}
    moderate = build_list(standard, strictness="moderate")
    assert {e.severity for e in moderate} == {"strong", "slur"}


def test_customized_removes_and_adds(standard):
    user = UserList(remove=["damn"], add=[Entry("frick", severity="mild", source="user")])
    words = {e.word for e in build_list(standard, "customized", "strict", user)}
    assert "damn" not in words and "frick" in words and "hell" in words


def test_user_words_ignore_strictness(standard):
    user = UserList(add=[Entry("frick", severity="mild", source="user")])
    words = {e.word for e in build_list(standard, "customized", "light", user)}
    assert "frick" in words


def test_mylist_only_user_words(standard):
    user = UserList(add=[Entry("spoiler", source="user")])
    assert [e.word for e in build_list(standard, "mylist", "strict", user)] == ["spoiler"]


# --- matching -------------------------------------------------------------

def test_basic_and_variants(standard):
    r = censor_string("Damn it, that's bullshit!", m(standard))
    assert r.text == "D*** it, that's b*******!"


def test_no_substring_matches(standard):
    text = "The class will assess Scunthorpe hello shell"
    assert censor_string(text, m(standard)).text == text


@pytest.mark.parametrize("evasion", ["f.u.c.k", "sh1t", "f*ck", "sh!t", "b-i-t-c-h", "@ss"])
def test_evasions(standard, evasion):
    assert censor_string(f"you {evasion} now", m(standard)).matches, evasion


def test_phrase_is_one_match(standard):
    r = censor_string("what a son of a bitch", m(standard))
    assert len(r.matches) == 1 and r.matches[0].text == "son of a bitch"


def test_trailing_exclamation_kept(standard):
    assert censor_string("damn!", m(standard)).text == "d***!"


def test_stars_only_is_not_a_word(standard):
    assert censor_string("rated ****", m(standard)).matches == []


def test_normalize():
    assert normalize("F.U.C.K") == "fuck"
    assert normalize("$h1t") == "shit"


# --- effects --------------------------------------------------------------

def test_effects():
    assert apply_effect("damn", "stars") == "d***"
    assert apply_effect("son of a bitch", "full") == "*** ** * *****"
    assert apply_effect("damn", "symbol") == "♪"
    assert apply_effect("DAMN", "replace", "darn") == "DARN"
    assert apply_effect("Damn", "replace", "darn") == "Darn"


def test_mask_for_reports():
    assert mask("fucking") == "f******"


# --- formats --------------------------------------------------------------

def test_json_values_only(standard):
    src = json.dumps({"shit": "oh shit", "n": 3, "list": ["damn", True]})
    out = json.loads(censor_file_text(src, "json", m(standard)).text)
    assert out == {"shit": "oh s***", "n": 3, "list": ["d***", True]}


def test_srt_keeps_timestamps(standard):
    srt = "1\n00:00:01,000 --> 00:00:02,000\nWhat the hell\n\n2\n00:00:03,000 --> 00:00:04,500\nfine\n"
    r = censor_file_text(srt, "srt", m(standard))
    assert r.text == srt.replace("hell", "h***")
    # match positions point into the whole file, not just the caption line
    assert srt[int(r.matches[0].start):int(r.matches[0].end)] == "hell"


def test_tokenize_offsets():
    toks = tokenize("hi there")
    assert [(t.text, t.start, t.end) for t in toks] == [("hi", 0, 2), ("there", 3, 8)]
