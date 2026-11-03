// Stable across identical paragraphs moving within a heading, and shared with Python exports.
export function reportAnchors(markdown: string, section: string): string[] {
  const counts = new Map<string, number>();
  const headings: { level: number; title: string }[] = [];
  return markdown.split('\n').map((raw) => {
    const line = raw.trim(),
      heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      while (
        headings.length &&
        headings[headings.length - 1].level >= heading[1].length
      )
        headings.pop();
      headings.push({ level: heading[1].length, title: heading[2] });
    }
    const identity = JSON.stringify([
      section,
      headings.map((h) => h.title),
      line,
    ]);
    let hash = 2166136261;
    for (const byte of new TextEncoder().encode(identity)) {
      hash = Math.imul(hash ^ byte, 16777619) >>> 0;
    }
    const id = hash.toString(16).padStart(8, '0'),
      occurrence = counts.get(id) ?? 0;
    counts.set(id, occurrence + 1);
    return `a_${id}_${occurrence}`;
  });
}
