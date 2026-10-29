import type { AIRun } from '../../api/aiChat';

type Part = { kind: 'thought'; id: string; text: string } | { kind: 'tool'; id: string; event: AIRun['tool_events'][number] };

export function activityTimeline(run: AIRun): Part[] | null {
  if (!run.tool_events.length || run.tool_events.some(event => !Number.isInteger(event.reasoning_offset))) return null;
  // Python offsets count Unicode characters; JS string offsets count UTF-16 units.
  const characters = Array.from(run.reasoning || '');
  const parts: Part[] = [];
  let start = 0;
  for (const event of run.tool_events) {
    const end = Math.max(start, Math.min(event.reasoning_offset!, characters.length));
    const text = characters.slice(start, end).join('');
    if (text.trim()) parts.push({ kind: 'thought', id: 'thought-' + event.id, text });
    parts.push({ kind: 'tool', id: event.id, event });
    start = end;
  }
  const text = characters.slice(start).join('');
  if (text.trim()) parts.push({ kind: 'thought', id: 'thought-tail', text });
  return parts;
}
