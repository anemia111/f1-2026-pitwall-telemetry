import { useEffect, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import { n } from './api';

export type Series = { key: string; label: string; color: string; values: (number | null | undefined)[] };
const PADDING = { left: 50, right: 22, top: 12, bottom: 29 };

export function Chart({ x, series, unit, name }: { x: number[]; series: Series[]; unit: string; name: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [size, resize] = useState({ width: 0, height: 225 });
  const [windowRange, setRange] = useState<[number, number] | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [off, setOff] = useState<string[]>([]);
  const drag = useRef<{ client: number; range: [number, number] } | null>(null);
  const left = x[0] ?? 0;
  const right = Math.max(left + .01, x[x.length - 1] ?? 1);
  const range: [number, number] = windowRange ?? [left, right];
  const visible = series.filter(s => !off.includes(s.key));
  const span = range[1] - range[0];
  const plotWidth = Math.max(1, size.width - PADDING.left - PADDING.right);
  const plotHeight = size.height - PADDING.top - PADDING.bottom;
  const index = cursor == null || !x.length ? -1 : nearest(x, range[0] + cursor * span);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(([r]) => resize({ width: r.contentRect.width, height: r.contentRect.height }));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    function zoom(e: WheelEvent) {
      if (!e.ctrlKey && !e.altKey) return;
      e.preventDefault();
      const box = node!.getBoundingClientRect();
      const anchor = Math.max(0, Math.min(1, (e.clientX - box.left - PADDING.left) / plotWidth));
      const target = Math.min(right - left, Math.max((right - left) / 80, span * Math.exp(e.deltaY * .0025)));
      if (target >= right - left) { setRange(null); return; }
      const min = Math.max(left, Math.min(right - target, range[0] + anchor * (span - target)));
      setRange([min, min + target]);
    }
    node.addEventListener('wheel', zoom, { passive: false });
    return () => node.removeEventListener('wheel', zoom);
  }, [left, right, span, range, plotWidth]);

  useEffect(() => {
    const node = ref.current;
    const ctx = node?.getContext('2d');
    if (!node || !ctx || !size.width) return;
    const pixelRatio = Math.min(2, window.devicePixelRatio || 1);
    node.width = Math.round(size.width * pixelRatio);
    node.height = Math.round(size.height * pixelRatio);
    ctx.scale(pixelRatio, pixelRatio);
    const px = (v: number) => PADDING.left + (v - range[0]) / span * plotWidth;
    let min = Infinity, max = -Infinity;
    for (const s of visible) {
      s.values.forEach((v, i) => {
        if (v != null && Number.isFinite(v) && x[i] >= range[0] && x[i] <= range[1]) {
          min = Math.min(min, v); max = Math.max(max, v);
        }
      });
    }
    if (!Number.isFinite(min)) { min = 0; max = 1; }
    const margin = Math.max((max - min) * .1, Math.abs(max) * .015, .01);
    min -= margin; max += margin;
    const py = (v: number) => PADDING.top + (max - v) / (max - min) * plotHeight;
    ctx.font = '11px Consolas, monospace';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 5; i++) {
      const y = PADDING.top + i * plotHeight / 5;
      ctx.strokeStyle = '#263140';
      ctx.beginPath(); ctx.moveTo(PADDING.left, y); ctx.lineTo(PADDING.left + plotWidth, y); ctx.stroke();
      ctx.fillStyle = '#8f9db1';
      ctx.textAlign = 'right';
      ctx.fillText(n(max - i * (max - min) / 5, max - min < 5 ? 2 : 0), PADDING.left - 6, y + 3);
      const v = range[0] + i * span / 5;
      ctx.textAlign = 'center';
      ctx.fillText(`${n(v, span < 5 ? 1 : 0)}${unit}`, px(v), size.height - 8);
    }
    ctx.save();
    ctx.beginPath(); ctx.rect(PADDING.left, PADDING.top, plotWidth, plotHeight); ctx.clip();
    for (const s of visible) {
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 1.7;
      ctx.beginPath();
      let pen = false;
      s.values.forEach((v, i) => {
        if (v == null || !Number.isFinite(v) || x[i] == null) { pen = false; return; }
        if (pen) ctx.lineTo(px(x[i]), py(v)); else ctx.moveTo(px(x[i]), py(v));
        pen = true;
      });
      ctx.stroke();
    }
    if (index >= 0) {
      const cx = px(x[index]);
      ctx.strokeStyle = '#d7e1ee';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(cx, PADDING.top); ctx.lineTo(cx, PADDING.top + plotHeight); ctx.stroke();
    }
    ctx.restore();
  }, [size, range, plotWidth, plotHeight, series, x, index, off, unit, span, visible]);

  function point(e: PointerEvent<HTMLCanvasElement>) {
    const fraction = (e.clientX - e.currentTarget.getBoundingClientRect().left - PADDING.left) / plotWidth;
    setCursor(Math.min(1, Math.max(0, fraction)));
    if (drag.current && span < right - left) {
      const [first, last] = drag.current.range;
      const delta = (drag.current.client - e.clientX) / plotWidth * (last - first);
      const begin = Math.max(left, Math.min(right - span, first + delta));
      setRange([begin, begin + span]);
    }
  }

  function zoomIn() {
    const middle = (range[0] + range[1]) / 2;
    const quarter = Math.max((right - left) / 160, span / 4);
    setRange([middle - quarter, middle + quarter]);
  }

  return <section className="panel chart">
    <div className="panel-head"><h3>{name}</h3><div className="controls">
      <button onClick={zoomIn} aria-label={name + ' 拡大'}>＋</button>
      <button onClick={() => setRange(null)}>全範囲</button>
    </div></div>
    <div className="legend">{series.map(s => <button key={s.key} aria-pressed={!off.includes(s.key)}
      onClick={() => setOff(old => old.includes(s.key) ? old.filter(k => k !== s.key) : [...old, s.key])}>
      <i style={{ background: s.color }} />{s.label}</button>)}</div>
    {!x.length && <p className="empty">サンプル待ち</p>}
    <canvas ref={ref} role="img" aria-label={name} onPointerMove={point}
      onPointerDown={e => { e.currentTarget.setPointerCapture(e.pointerId); drag.current = { client: e.clientX, range }; point(e); }}
      onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}
      onPointerLeave={() => { if (!drag.current) setCursor(null); }} />
    <div className="readout">{index >= 0 ? <>
      <strong>{n(x[index], 1)} {unit}</strong>{visible.map(s => <span key={s.key}>{s.label} {n(s.values[index], 2)}</span>)}
    </> : <span>Ctrl / Alt + スクロールで拡大縮小 · ドラッグで移動</span>}</div>
  </section>;
}

function nearest(values: number[], target: number): number {
  let lo = 0, hi = values.length - 1;
  while (lo < hi) {
    const m = (lo + hi) >>> 1;
    if (values[m] < target) lo = m + 1;
    else hi = m;
  }
  return lo > 0 && Math.abs(values[lo - 1] - target) < Math.abs(values[lo] - target) ? lo - 1 : lo;
}
