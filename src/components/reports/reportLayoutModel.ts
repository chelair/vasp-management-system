export const W = 960,
  H = 480;
export const kinds = {
  text: '文本框',
  rectangle: '矩形',
  rounded: '圆角矩形',
  square: '正方形',
  circle: '圆形',
  ellipse: '椭圆形',
  triangle: '三角形',
  diamond: '菱形',
  line: '直线',
  arrow: '单向箭头',
  'double-arrow': '双向箭头',
};
export type Kind = keyof typeof kinds;
export interface LayoutStyle {
  fill: string;
  fill_opacity: number;
  stroke: string;
  stroke_width: number;
  stroke_opacity: number;
  dash: 'solid' | 'dashed' | 'dotted';
  arrow_start: boolean;
  arrow_end: boolean;
  color: string;
  font_size: number;
  font_weight: 400 | 500 | 600 | 700 | 800;
  italic: boolean;
  align: 'left' | 'center' | 'right';
  vertical: 'start' | 'center' | 'end';
  padding: number;
}
export interface LayoutObject {
  id: string;
  report_id: string;
  region: string;
  kind: Kind;
  x: number;
  y: number;
  width: number;
  height: number;
  rotation: number;
  dx: number;
  dy: number;
  text: string;
  z: number;
  style: LayoutStyle;
  created_at: string;
  updated_at: string;
}
export interface Layout {
  version: 1;
  revision: number;
  objects: LayoutObject[];
  snapshot_warning?: string;
}
export const emptyLayout = (): Layout => ({
  version: 1,
  revision: 0,
  objects: [],
});
export const isLine = (o: LayoutObject) =>
  ['line', 'arrow', 'double-arrow'].includes(o.kind);
export const clamp = (v: number, lo: number, hi: number) =>
  Math.max(lo, Math.min(v, hi));
export const newObjectId = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) =>
    value.toString(16).padStart(2, '0'),
  ).join('');

export function makeObject(
  kind: Kind,
  report_id: string,
  region: string,
  z: number,
): LayoutObject {
  const square = kind === 'circle' || kind === 'square';
  return {
    id: newObjectId(),
    report_id,
    region,
    kind,
    x: 40,
    y: 50,
    width: square ? 160 : 240,
    height: 160,
    rotation: 0,
    dx: 180,
    dy: 0,
    text: kind === 'text' ? '双击编辑文字' : '',
    z,
    created_at: '',
    updated_at: '',
    style: {
      fill: '#ffffff',
      fill_opacity: kind === 'text' ? 0.85 : 0.65,
      stroke: '#3f6fe0',
      stroke_width: 2,
      stroke_opacity: 1,
      dash: 'solid',
      arrow_start: kind === 'double-arrow',
      arrow_end: true,
      color: '#233043',
      font_size: 24,
      font_weight: 400,
      italic: false,
      align: 'left',
      vertical: 'center',
      padding: 12,
    },
  };
}
export function fit(o: LayoutObject): LayoutObject {
  if (isLine(o)) {
    const x = clamp(o.x, Math.max(0, -o.dx), Math.min(W, W - o.dx)),
      y = clamp(o.y, Math.max(0, -o.dy), Math.min(H, H - o.dy));
    return { ...o, x, y, rotation: 0 };
  }
  let width = clamp(o.width, 24, W),
    height = clamp(o.height, 24, H);
  if (o.kind === 'circle' || o.kind === 'square')
    width = height = Math.min(width, height);
  const r = (o.rotation * Math.PI) / 180,
    c = Math.abs(Math.cos(r)),
    s = Math.abs(Math.sin(r));
  const ratio = Math.min(
    1,
    W / (width * c + height * s),
    H / (width * s + height * c),
  );
  width *= ratio;
  height *= ratio;
  const halfW = (width * c + height * s) / 2,
    halfH = (width * s + height * c) / 2;
  return {
    ...o,
    width,
    height,
    x: clamp(o.x + width / 2, halfW, W - halfW) - width / 2,
    y: clamp(o.y + height / 2, halfH, H - halfH) - height / 2,
  };
}
export function textHeight(o: LayoutObject): number {
  const canvas = document.createElement('canvas'),
    ctx = canvas.getContext('2d');
  if (!ctx) return o.height;
  ctx.font = `${o.style.italic ? 'italic' : 'normal'} ${o.style.font_weight} ${o.style.font_size}px Arial`;
  const max = Math.max(1, o.width - o.style.padding * 2);
  let lines = 0;
  for (const paragraph of o.text.split('\n')) {
    let used = 0;
    lines++;
    for (const char of paragraph) {
      const size = ctx.measureText(char).width;
      if (used + size > max) {
        lines++;
        used = 0;
      }
      used += size;
    }
  }
  return lines * o.style.font_size * 1.35 + o.style.padding * 2;
}
