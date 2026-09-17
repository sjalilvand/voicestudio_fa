const MAX_CRASH_TAIL_CHARS = 1200;
const CHAIN_MARKER_RE =
  /^(?:The above exception was the direct cause of the following exception|During handling of the above exception, another exception occurred):?$/;

/** The error line that ends the FIRST block of a chained traceback — i.e. the
 *  original cause. Empty string when `text` is not a chained traceback. */
export function rootCauseLine(text) {
  const lines = text.split('\n');
  const marker = lines.findIndex((l) => CHAIN_MARKER_RE.test(l.trim()));
  if (marker <= 0) return '';
  // Walk back past the marker's blank line to the last non-indented line —
  // traceback frames are indented, the exception line is not.
  for (let i = marker - 1; i >= 0; i -= 1) {
    const line = lines[i];
    if (line.trim() && !/^\s/.test(line)) return line.trim();
  }
  return '';
}

// Below this much room for actual log output, the root-cause header stops being
// worth its cost — a labelled line with almost nothing under it is harder to
// act on than the raw newest output.
const MIN_TAIL_CHARS = 400;

/** Bound the crash stderr to `max` characters, keeping the newest end AND — for
 *  a chained traceback — the root cause that would otherwise be cut.
 *
 *  The result never exceeds `max`: the prefix is budgeted for BEFORE slicing,
 *  not added on top of a full-size tail. */
export function clampCrashTail(text, max = MAX_CRASH_TAIL_CHARS) {
  if (text.length <= max) return text;

  const PLAIN = '… (truncated)';
  const plainTail = () => `${PLAIN}\n${text.slice(-Math.max(0, max - PLAIN.length - 1))}`;

  const root = rootCauseLine(text);
  if (!root) return plainTail();

  const prefix = `${root}\n… (truncated — chained traceback; the line above is the original cause)\n`;
  const room = max - prefix.length;
  if (room < MIN_TAIL_CHARS) return plainTail();

  const kept = text.slice(-room);
  // Already visible in what we keep — repeating it is noise, and the budget is
  // better spent on more log.
  if (kept.includes(root)) return plainTail();
  return prefix + kept;
}
