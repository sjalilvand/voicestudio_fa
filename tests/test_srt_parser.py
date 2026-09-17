"""Unit tests for the SRT parser used by /dub/import-srt."""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from services.srt_parser import parse_srt  # noqa: E402


def test_parses_a_well_formed_srt_file():
    srt = """1
00:00:01,000 --> 00:00:04,500
Hello world.

2
00:00:05,250 --> 00:00:08,000
Second line here.
"""
    result = parse_srt(srt)
    assert result.skipped_cues == 0
    assert result.dropped_overlaps == 0
    assert len(result.segments) == 2
    assert result.segments[0]["start"] == 1.0
    assert result.segments[0]["end"] == 4.5
    assert result.segments[0]["text"] == "Hello world."
    assert result.segments[1]["start"] == 5.25
    assert result.segments[1]["text"] == "Second line here."


def test_joins_multi_line_cues_with_newline():
    srt = """1
00:00:01,000 --> 00:00:04,000
Line one
Line two
"""
    result = parse_srt(srt)
    assert result.segments[0]["text"] == "Line one\nLine two"


def test_accepts_dot_as_milliseconds_separator():
    # WebVTT-style timestamps inside an SRT file are common in the wild.
    srt = """1
00:00:01.500 --> 00:00:03.250
Dotty.
"""
    result = parse_srt(srt)
    assert result.segments[0]["start"] == 1.5
    assert result.segments[0]["end"] == 3.25


def test_handles_utf8_bom_at_start_of_file():
    srt = "﻿1\n00:00:01,000 --> 00:00:02,000\nBOM cue.\n"
    result = parse_srt(srt)
    assert len(result.segments) == 1
    assert result.segments[0]["text"] == "BOM cue."


def test_handles_crlf_line_endings():
    srt = "1\r\n00:00:01,000 --> 00:00:02,000\r\nWindows.\r\n\r\n"
    result = parse_srt(srt)
    assert len(result.segments) == 1


def test_skips_cue_with_non_positive_duration():
    srt = """1
00:00:05,000 --> 00:00:05,000
Zero duration.

2
00:00:06,000 --> 00:00:05,500
End before start.

3
00:00:07,000 --> 00:00:08,000
Good cue.
"""
    result = parse_srt(srt)
    assert result.skipped_cues == 2
    assert len(result.segments) == 1
    assert result.segments[0]["text"] == "Good cue."


def test_skips_cue_with_only_whitespace_body():
    srt = """1
00:00:01,000 --> 00:00:02,000


2
00:00:03,000 --> 00:00:04,000
Real text.
"""
    result = parse_srt(srt)
    assert result.skipped_cues == 1
    assert len(result.segments) == 1


def test_shifts_overlapping_cue_to_keep_both():
    # Cue 2 starts inside cue 1; we expect cue 2's start to be pushed
    # forward to cue 1's end so both still play, in order.
    srt = """1
00:00:01,000 --> 00:00:05,000
First.

2
00:00:03,000 --> 00:00:07,000
Second.
"""
    result = parse_srt(srt)
    assert len(result.segments) == 2
    assert result.segments[1]["start"] == 5.0
    assert result.segments[1]["end"] == 7.0
    assert result.dropped_overlaps == 0


def test_drops_overlap_that_would_have_negative_duration():
    srt = """1
00:00:01,000 --> 00:00:10,000
First.

2
00:00:03,000 --> 00:00:08,000
Second entirely inside first.
"""
    result = parse_srt(srt)
    assert len(result.segments) == 1
    assert result.dropped_overlaps == 1


def test_parses_missing_index_numbers():
    # No "1", "2" lines — just timings + text. This happens with some
    # subtitle editors that strip indices.
    srt = """00:00:01,000 --> 00:00:02,000
First.

00:00:03,000 --> 00:00:04,000
Second.
"""
    result = parse_srt(srt)
    assert len(result.segments) == 2


def test_returns_empty_result_for_empty_input():
    assert parse_srt("").segments == []
    assert parse_srt("").skipped_cues == 0


def test_blank_line_flood_parses_in_linear_time():
    # Regression: the timing-line regex used `^\s*` under re.MULTILINE, so at
    # every one of N line starts the engine consumed all remaining blank
    # lines before failing — quadratic. 20k blank lines already took ~1.7s
    # and a 2 MB blank-line file never returned, pinning the request thread
    # (reachable from /dub/import-srt with a mis-saved export, and from the
    # pasted-text endpoint). Horizontal-whitespace-only classes make it
    # linear: this input parses in milliseconds.
    import time

    srt = "1\n00:00:01,000 --> 00:00:02,000\nOnly cue.\n" + "\n" * 400_000
    started = time.monotonic()
    result = parse_srt(srt)
    elapsed = time.monotonic() - started
    assert len(result.segments) == 1
    assert result.segments[0]["text"] == "Only cue."
    # Pre-fix this was minutes; the bound is loose enough for a slow CI box
    # and still ~3 orders of magnitude under the quadratic behaviour.
    assert elapsed < 5.0, f"parse_srt took {elapsed:.1f}s — quadratic scan is back"


def test_timing_line_tolerates_leading_and_inner_spaces():
    # The linearity fix narrowed `\s*` to horizontal whitespace; indented
    # cues and extra spaces around the arrow must still parse.
    srt = "  \t00:00:01,000  -->  \t00:00:02,000\nIndented.\n"
    result = parse_srt(srt)
    assert len(result.segments) == 1
    assert result.segments[0]["text"] == "Indented."


def test_keeps_a_final_cue_that_is_only_a_number():
    # Regression: cue bodies are sliced up to the next timing line, which
    # swallows that cue's index, and the parser used to claw it back by
    # popping *every* trailing digit-only line. The last cue has no next
    # index to pop, so a closing "1999" was mistaken for one — the cue lost
    # its only line and was dropped as empty. Numeric-only dialogue is
    # everywhere in subtitles (a year, a score, a street number).
    srt = """1
00:00:01,000 --> 00:00:02,000
The year was

2
00:00:03,000 --> 00:00:04,000
1999
"""
    result = parse_srt(srt)
    assert result.skipped_cues == 0
    assert [s["text"] for s in result.segments] == ["The year was", "1999"]


def test_keeps_numeric_dialogue_in_an_index_less_file():
    # An index-less export has no index lines to strip at all, so a cue
    # ending in a number kept its text silently truncated — no skip counted,
    # so the import reported itself as lossless while dropping a line.
    srt = """00:00:01,000 --> 00:00:02,000
The answer is
42

00:00:03,000 --> 00:00:04,000
Next.
"""
    result = parse_srt(srt)
    assert [s["text"] for s in result.segments] == ["The answer is\n42", "Next."]


def test_keeps_numeric_text_when_the_blank_separator_is_missing():
    # Off-spec file with no blank line between cue text and the next index:
    # exactly one trailing index line may be reclaimed, never two.
    srt = """1
00:00:01,000 --> 00:00:02,000
100
2
00:00:03,000 --> 00:00:04,000
Hi
"""
    result = parse_srt(srt)
    assert [s["text"] for s in result.segments] == ["100", "Hi"]


def test_keeps_a_multi_line_numeric_countdown():
    # The old `while` loop popped digit lines until it hit a non-digit, so a
    # "3 / 2 / 1" countdown cue was consumed line by line and then dropped.
    srt = """1
00:00:01,000 --> 00:00:02,000
Ready?

2
00:00:03,000 --> 00:00:04,000
3
2
1
"""
    result = parse_srt(srt)
    assert [s["text"] for s in result.segments] == ["Ready?", "3\n2\n1"]


def test_non_ascii_numerals_are_dialogue_not_cue_indices():
    # `str.isdigit()` is True for Arabic-Indic and Devanagari numerals, which
    # SubRip never uses for indices but a 646-language dubbing app sees as
    # dialogue constantly.
    srt = """1
00:00:01,000 --> 00:00:02,000
١٩٩٩

2
00:00:03,000 --> 00:00:04,000
२०२६
"""
    result = parse_srt(srt)
    assert [s["text"] for s in result.segments] == ["١٩٩٩", "२०२६"]


def test_still_strips_the_index_line_swallowed_from_the_next_cue():
    # The guard against over-correcting: a numeric-bodied cue followed by
    # another must keep its own text and still not leak the next index.
    srt = """1
00:00:01,000 --> 00:00:02,000
1999

2
00:00:03,000 --> 00:00:04,000
Next.
"""
    result = parse_srt(srt)
    assert [s["text"] for s in result.segments] == ["1999", "Next."]


def test_segments_get_sequential_ids_and_required_fields():
    srt = """1
00:00:01,000 --> 00:00:02,000
A

2
00:00:03,000 --> 00:00:04,000
B
"""
    result = parse_srt(srt)
    for i, seg in enumerate(result.segments):
        assert seg["id"] == i
        assert seg["text"] == seg["text_original"]
        assert seg["speaker_id"] == "Speaker 1"


@pytest.mark.parametrize("first_index", ["", "1\n"])
def test_mixed_indexed_and_unindexed_cues_preserve_numbers(first_index):
    text = first_index + "00:00:01,000 --> 00:00:02,000\n42\n\n2\n00:00:03,000 --> 00:00:04,000\n1999\n\n00:00:05,000 --> 00:00:06,000\n3\n2\n1\n"
    assert [x["text"] for x in parse_srt(text).segments] == ["42", "1999", "3\n2\n1"]
