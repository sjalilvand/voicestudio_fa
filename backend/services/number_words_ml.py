"""Malayalam number words (cardinals, decimals, percentages).

``num2words`` has no Malayalam (``ml``) locale, so without this module
Malayalam text would reach the TTS engine with raw digits. The rendering here
is pure Python with no dependencies and is deliberately narrow, matching the
conservative scope of :mod:`services.text_normalization`: integers up to six
digits (Indian grouping with ``laksham``; crore-scale is out), decimals read
digit by digit, and percentages.

Output is Malayalam script only, words separated by single ASCII spaces, in
modern atomic-chillu spelling, with no digits and no joiner characters.
"""
from __future__ import annotations

_ZERO = "പൂജ്യം"
_UNITS = ["", "ഒന്ന്", "രണ്ട്", "മൂന്ന്", "നാല്", "അഞ്ച്", "ആറ്", "ഏഴ്", "എട്ട്", "ഒൻപത്"]
_TEENS = [
    "പത്ത്", "പതിനൊന്ന്", "പന്ത്രണ്ട്", "പതിമൂന്ന്", "പതിനാല്",
    "പതിനഞ്ച്", "പതിനാറ്", "പതിനേഴ്", "പതിനെട്ട്", "പത്തൊൻപത്",
]
# Indexed by the tens digit (2..9); entries 0 and 1 are unused.
_TENS = ["", "", "ഇരുപത്", "മുപ്പത്", "നാൽപത്", "അൻപത്", "അറുപത്", "എഴുപത്", "എൺപത്", "തൊണ്ണൂറ്"]
_TENS_PREFIX = ["", "", "ഇരുപത്തി", "മുപ്പത്തി", "നാൽപത്തി", "അൻപത്തി", "അറുപത്തി", "എഴുപത്തി", "എൺപത്തി", "തൊണ്ണൂറ്റി"]
# Indexed by the hundreds digit (1..9).
_HUNDREDS = ["", "നൂറ്", "ഇരുനൂറ്", "മുന്നൂറ്", "നാനൂറ്", "അഞ്ഞൂറ്", "അറുനൂറ്", "എഴുനൂറ്", "എണ്ണൂറ്", "തൊള്ളായിരം"]
_HUNDREDS_PREFIX = [
    "", "നൂറ്റി", "ഇരുനൂറ്റി", "മുന്നൂറ്റി", "നാനൂറ്റി", "അഞ്ഞൂറ്റി",
    "അറുനൂറ്റി", "എഴുനൂറ്റി", "എണ്ണൂറ്റി", "തൊള്ളായിരത്തി",
]
# "N thousand" for N = 1..19 (irregular, so tabulated; index 0 unused).
_THOUSANDS_SMALL = [
    "", "ആയിരം", "രണ്ടായിരം", "മൂവായിരം", "നാലായിരം", "അയ്യായിരം", "ആറായിരം",
    "ഏഴായിരം", "എണ്ണായിരം", "ഒൻപതിനായിരം", "പതിനായിരം", "പതിനൊന്നായിരം",
    "പന്ത്രണ്ടായിരം", "പതിമൂന്നായിരം", "പതിനാലായിരം", "പതിനയ്യായിരം",
    "പതിനാറായിരം", "പതിനേഴായിരം", "പതിനെട്ടായിരം", "പത്തൊൻപതിനായിരം",
]
# Whole tens of thousands, indexed by the tens digit (2..9).
_THOUSANDS_TENS = [
    "", "", "ഇരുപതിനായിരം", "മുപ്പതിനായിരം", "നാൽപതിനായിരം", "അൻപതിനായിരം",
    "അറുപതിനായിരം", "എഴുപതിനായിരം", "എൺപതിനായിരം", "തൊണ്ണൂറായിരം",
]
# "unit thousand" after a tens prefix, indexed by the unit digit (1..9).
_THOUSANDS_AFTER_TENS = [
    "", "ഒന്നായിരം", "രണ്ടായിരം", "മൂവായിരം", "നാലായിരം", "അയ്യായിരം",
    "ആറായിരം", "ഏഴായിരം", "എട്ടായിരം", "ഒൻപതിനായിരം",
]
_LAKH = "ലക്ഷം"
_ONE_BEFORE_LAKH = "ഒരു"
_DECIMAL_POINT = "ദശാംശം"
_PERCENT = "ശതമാനം"

# CLEAN-ROOM (spec W10-ml §1)
