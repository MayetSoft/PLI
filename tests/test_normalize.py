"""Property tests for email normalisation.

Normalisation is identical for src and dst by construction (one function),
but it must also be canonical: any two spellings a real person might use
for the same mailbox must collapse to the same string, or reciprocity
silently fails. This is where the bug will be.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pli.normalize import is_rfc_shaped, normalise_email

LOCAL_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"

locals_st = st.text(alphabet=LOCAL_CHARS, min_size=1, max_size=20)
segments_st = st.lists(
    st.text(alphabet=LOCAL_CHARS, min_size=1, max_size=6), min_size=2, max_size=4
)
domains_st = st.sampled_from(["example.edu", "etu.uca.fr", "mail.example.org"])
tags_st = st.text(alphabet=LOCAL_CHARS + ".", min_size=0, max_size=10)


@given(locals_st, domains_st)
def test_idempotent(local, domain):
    once = normalise_email(f"{local}@{domain}")
    assert normalise_email(once) == once


@given(locals_st, domains_st)
def test_case_and_whitespace_insensitive(local, domain):
    email = f"{local}@{domain}"
    assert normalise_email(f"  {email.upper()}  ") == normalise_email(email)


@given(locals_st, tags_st, domains_st)
def test_plus_tag_stripped(local, tag, domain):
    assert normalise_email(f"{local}+{tag}@{domain}") == normalise_email(f"{local}@{domain}")


@given(segments_st)
def test_gmail_dots_folded(segments):
    dotted = ".".join(segments)
    folded = "".join(segments)
    assert normalise_email(f"{dotted}@gmail.com") == normalise_email(f"{folded}@gmail.com")


@given(locals_st)
def test_googlemail_folds_to_gmail(local):
    assert normalise_email(f"{local}@googlemail.com") == normalise_email(f"{local}@gmail.com")


@given(segments_st, domains_st)
def test_non_gmail_dots_are_significant(segments, domain):
    dotted = ".".join(segments)
    folded = "".join(segments)
    assert normalise_email(f"{dotted}@{domain}") != normalise_email(f"{folded}@{domain}")


@given(locals_st, locals_st, domains_st)
def test_src_dst_symmetry(local_a, local_b, domain):
    """The exact reciprocity condition: however each side spells the
    other's address, both spellings of the same mailbox meet in the middle."""
    a_types = f" {local_b.upper()}+crush@{domain} "
    b_canonical = f"{local_b}@{domain}"
    assert normalise_email(a_types) == normalise_email(b_canonical)


@pytest.mark.parametrize(
    "bad", ["", "no-at-sign", "@nolocal.example", "nodomain@", "a@b", "two@@ats.example", "sp ace@x.example"]
)
def test_rejects_non_rfc_shapes(bad):
    assert not is_rfc_shaped(bad)
    with pytest.raises(ValueError):
        normalise_email(bad)


def test_plus_only_local_rejected():
    with pytest.raises(ValueError):
        normalise_email("+tag@example.edu")
