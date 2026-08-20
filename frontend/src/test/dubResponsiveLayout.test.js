import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8');

describe('responsive dub timeline sizing', () => {
  it('releases both forced track dimensions inside the narrow workspace', () => {
    const narrow = css.match(
      /@container dub-shell \(max-width: 1080px\) \{[\s\S]*?\.dub-panel-left \.seg-track \{([^}]*)\}/,
    );

    expect(narrow?.[1]).toMatch(/flex:\s*0 0 auto !important/);
    expect(narrow?.[1]).toMatch(/height:\s*auto/);
  });
});
