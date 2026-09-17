// Sentence-aware splitter for the "Paste & auto-split" panel. Walks the text
// and breaks at the closest sentence boundary that keeps each chunk under
// `maxChars`. Falls back to whitespace, then to the hard cap.
export function splitIntoChunks(text, maxChars) {
  const out = [];
  const clean = String(text || '')
    .replace(/\r\n/g, '\n')
    .trim();
  if (!clean) return out;
  const max = Math.max(40, Math.min(2000, maxChars | 0));
  let i = 0;
  while (i < clean.length) {
    const remain = clean.length - i;
    if (remain <= max) {
      out.push(clean.slice(i).trim());
      break;
    }
    const window = clean.slice(i, i + max);
    let cut = -1;
    for (let j = window.length - 1; j > Math.floor(max * 0.4); j--) {
      if (/[.!?\u3002\uFF01\uFF1F]/.test(window[j])) {
        cut = j + 1;
        break;
      }
    }
    if (cut < 0) {
      for (let j = window.length - 1; j > Math.floor(max * 0.4); j--) {
        if (/\s/.test(window[j])) {
          cut = j;
          break;
        }
      }
    }
    if (cut < 0) cut = max;
    out.push(clean.slice(i, i + cut).trim());
    i += cut;
  }
  return out.filter(Boolean);
}
