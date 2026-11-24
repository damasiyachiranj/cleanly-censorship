import json

import pytest

from cleanly.matcher import Matcher, normalize, tokenize
from cleanly.text import apply_effect, censor_file_text, censor_string, mask
from cleanly.wordlist import Entry, UserList, build_list, load_builtin


@pytest.fixture(scope="module")
def standard():
    return load_builtin("en")


def m(builtin, mode="strict", user=None):
    return Matcher(build_list(builtin, mode, user))


def words_in(entries):
    return {e.word for e in entries}


# --- modes ----------------------------------------------------------------

def test_strict_is_everything(standard):
    assert len(build_list(standard, "strict")) == len(standard)


def test_standard_is_adult_subset(standard):
    adult = words_in(build_list(standard, "standard"))
    assert {"fuck", "shit", "cocaine", "kill yourself"} <= adult
    assert not {"stupid", "damn", "beer", "kill", "weed"} & adult
    assert adult < words_in(standard)


def test_kids_only_words_pass_in_standard(standard):
    text = "that's stupid, grab a beer"
    assert censor_string(text, m(standard, "standard")).text == text
    assert censor_string(text, m(standard, "strict")).text == "that's s*****, grab a b***"


def test_customize_base_remove_add(standard):
    user = UserList(base="standard", remove=["shit"], add=[Entry("frick", source="user")])
    words = words_in(build_list(standard, "customize", user))
    assert "shit" not in words and "frick" in words and "fuck" in words and "stupid" not in words


def test_customize_from_strict(standard):
    user = UserList(base="strict", remove=["hell"])
    words = words_in(build_list(standard, "customize", user))
    assert "hell" not in words and "stupid" in words


def test_customize_remove_one_variant(standard):
    user = UserList(base="strict", remove=["damned"])
    r = censor_string("damn, damned", m(standard, "customize", user))
    assert r.text == "d***, damned"


def test_userlist_roundtrip(tmp_path):
    u = UserList(base="strict", remove=["hell"], add=[Entry("frick", source="user")])
    u.save(tmp_path / "l.json")
    back = UserList.load(tmp_path / "l.json")
    assert back.base == "strict" and back.remove == ["hell"] and back.add[0].word == "frick"


def test_every_entry_valid(standard):
    for e in standard:
        assert e.level in ("standard", "strict") and e.category != "custom", e.word


# --- matching -------------------------------------------------------------

def test_basic_and_variants(standard):
    r = censor_string("Damn it, that's bullshit!", m(standard))
    assert r.text == "D*** it, that's b*******!"


def test_no_substring_matches(standard):
    text = "The class will assess Scunthorpe hello shell skill"
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


@pytest.mark.parametrize("text,how", [
    ("damn", "exact"), ("bullshit", "variant"), ("sh1t", "disguised"),
    ("f*ck", "wildcard"), ("son of a bitch", "phrase"),
])
def test_match_reason(standard, text, how):
    assert censor_string(text, m(standard)).matches[0].how == how


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
