import type { CSSProperties, ReactNode } from 'react';
import { isLine, type LayoutObject } from './reportLayoutModel';

export default function ReportLayoutShape({
  o,
  children,
}: {
  o: LayoutObject;
  children?: ReactNode;
}) {
  const s = o.style,
    w = o.width,
    h = o.height;
  const attrs = {
    fill: s.fill,
    fillOpacity: s.fill_opacity,
    stroke: s.stroke,
    strokeWidth: s.stroke_width,
    strokeOpacity: s.stroke_opacity,
    strokeDasharray: { solid: '', dashed: '10 6', dotted: '2 5' }[s.dash],
  };
  if (isLine(o)) {
    const length = Math.hypot(o.dx, o.dy) || 1,
      ux = o.dx / length,
      uy = o.dy / length,
      a = Math.max(10, s.stroke_width * 3);
    return (
      <>
        <path d={`M0 0 L${o.dx} ${o.dy}`} {...attrs} fill="none" />
        {[false, true].map((end) => {
          if (o.kind === 'line' || !(end ? s.arrow_end : s.arrow_start))
            return null;
          const px = end ? o.dx : 0,
            py = end ? o.dy : 0,
            sign = end ? 1 : -1,
            bx = px - sign * ux * a,
            by = py - sign * uy * a;
          return (
            <polygon
              key={String(end)}
              points={`${px},${py} ${bx - (uy * a) / 2},${by + (ux * a) / 2} ${bx + (uy * a) / 2},${by - (ux * a) / 2}`}
              fill={s.stroke}
              fillOpacity={s.stroke_opacity}
            />
          );
        })}
      </>
    );
  }
  let shape: ReactNode;
  if (o.kind === 'circle' || o.kind === 'ellipse')
    shape = (
      <ellipse
        cx={w / 2}
        cy={h / 2}
        rx={w / 2 - s.stroke_width / 2}
        ry={h / 2 - s.stroke_width / 2}
        {...attrs}
      />
    );
  else if (o.kind === 'triangle' || o.kind === 'diamond')
    shape = (
      <polygon
        points={
          o.kind === 'triangle'
            ? `${w / 2},0 ${w},${h} 0,${h}`
            : `${w / 2},0 ${w},${h / 2} ${w / 2},${h} 0,${h / 2}`
        }
        {...attrs}
      />
    );
  else
    shape = (
      <rect
        x={s.stroke_width / 2}
        y={s.stroke_width / 2}
        width={w - s.stroke_width}
        height={h - s.stroke_width}
        rx={o.kind === 'rounded' ? 18 : 0}
        {...attrs}
      />
    );
  const style: CSSProperties = {
    boxSizing: 'border-box',
    width: '100%',
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    justifyContent: s.vertical,
    padding: s.padding,
    color: s.color,
    font: `${s.italic ? 'italic' : 'normal'} ${s.font_weight} ${s.font_size}px/1.35 Arial,"Microsoft YaHei",sans-serif`,
    textAlign: s.align,
    whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere',
    overflow: 'visible',
  };
  return (
    <>
      {shape}
      <foreignObject width={w} height={h}>
        <div {...{ xmlns: 'http://www.w3.org/1999/xhtml' }} style={style}>
          {children ?? <div>{o.text}</div>}
        </div>
      </foreignObject>
    </>
  );
}
