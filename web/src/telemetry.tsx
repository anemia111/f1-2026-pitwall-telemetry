import { useMemo, useState } from 'react';
import { clock, lapTime, n, seconds, useQuery } from './api';
import { Chart } from './chart';
import type { Car, Comparison, Lap, Metrics, Sample, Snapshot, Zone } from './types';

export const COLORS = ['#58d6eb', '#f6bf60', '#f78292', '#9fa6ff'];
export const carName = (car: Car | undefined) => car?.name ?? (car ? `CAR ${car.id + 1}` : 'N/A');
export const pos = (c: Car) => c.result?.position || c.lap?.carPosition;
export const flag = (s: Snapshot) => s.red ? '赤旗' :
  s.session ? ['GREEN', 'SC', 'VSC', 'FORMATION'][s.session.safetyCarStatus] ?? 'N/A' : 'N/A';
export const split = (v: number | null | undefined) => v == null ? 'N/A' : '+' + seconds(v);

export function Metric({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong>{hint && <small>{hint}</small>}</div>;
}
export function CarSelect({ cars, selected, onSelect, label = 'ドライバー' }: {
  cars: Car[]; selected: number; onSelect: (id: number) => void; label?: string;
}) {
  return <label className="field compact">{label}<select value={selected} onChange={e => onSelect(Number(e.target.value))}>
    {!cars.some(c => c.id === selected) && <option value={selected}>N/A</option>}
    {cars.map(c => <option value={c.id} key={c.id}>{c.participant?.raceNumber ? `#${c.participant.raceNumber} · ` : ''}{carName(c)}</option>)}
  </select></label>;
}

export function Timing({ snap, selected, select }: { snap: Snapshot; selected: number; select: (id: number) => void }) {
  return <section className="panel timing">
    <div className="panel-head"><div><div className="eyebrow">TIMING FEED</div><h2>ライブタイミング</h2></div>
      <span className="tag">{snap.cars.length} / 24 CARS</span></div>
    <div className="table-scroll"><table>
      <thead><tr>{['POS', 'DRIVER / TEAM', 'TYRE', 'AGE', 'LAP', 'BEST', 'LAST', 'S1', 'S2', 'S3 LAST', 'AHEAD', 'BEHIND', 'LEADER', 'STATE', 'AERO', 'OT'].map(x => <th scope="col" key={x}>{x}</th>)}</tr></thead>
      <tbody>{snap.cars.map(c => {
        const l = c.lap, a = c.aero;
        const state = l?.resultStatus === 4 || l?.resultStatus === 7 ? 'DNF'
          : l?.resultStatus === 5 ? 'DSQ' : c.result?.resultStatus === 3 || l?.resultStatus === 3 ? 'FIN'
          : l?.pitStatus ? 'PIT' : l?.penalties ? `+${l.penalties}s PEN` : l?.resultStatus === 2 ? 'TRACK' : 'N/A';
        return <tr key={c.id} className={selected === c.id ? 'selected' : ''}>
          <td className="position">{n(pos(c))}</td>
          <td><button className="driver" onClick={() => select(c.id)} aria-pressed={selected === c.id}>
            <b>{carName(c)}</b><small>#{n(c.participant?.raceNumber)} · {c.team ?? 'N/A'}{c.id === snap.player ? ' · PLAYER' : ''}</small>
          </button></td>
          <td><span className={`compound tyre-${c.tyre ?? 'none'}`}>{c.tyre ?? 'N/A'}</span></td>
          <td>{n(c.status?.tyresAgeLaps)}</td><td>{n(l?.currentLapNum ?? c.result?.numLaps)}</td>
          <td className="violet">{lapTime(c.best)}</td><td>{lapTime(l?.lastLapTimeInMS)}</td>
          <td>{seconds(l?.sector1)}</td><td>{seconds(l?.sector2)}</td><td>{seconds(l?.previousSector3)}</td>
          <td>{split(l?.frontGap)}</td><td>{split(l?.rearGap)}</td><td>{pos(c) === 1 ? 'LEAD' : split(l?.leaderGap)}</td>
          <td className={state === 'TRACK' ? 'muted' : 'amber'}>{state}</td>
          <td>{a?.['2026Regulations'] ? a.activeAeroMode === 1 ? 'STR' : a.activeAeroMode === 0 ? 'COR' : 'N/A' : 'N/A'}</td>
          <td className={a?.overtakeActive ? 'accent' : ''}>{a?.['2026Regulations'] ? a.overtakeActive ? 'ON' : a.overtakeAvailable ? 'RDY' : 'OFF' : 'N/A'}</td>
        </tr>;
      })}</tbody>
    </table></div>
    {!snap.cars.length && <p className="empty">UDP 2026 の有効なデータを待っています。</p>}
  </section>;
}

const eventLabels: Record<string, string> = {
  SSTA: 'セッション開始', SEND: 'セッション終了', SCAR: 'セーフティカー', RDFL: '赤旗',
  PENA: 'ペナルティ', RTMT: 'リタイア', FTLP: 'ファステストラップ', OVTK: 'オーバーテイク',
  FLBK: 'フラッシュバック', COLL: '接触', CHQF: 'チェッカー', LGOT: 'スタート',
};

export function EventList({ events, jump }: { events: Snapshot['events']; jump?: (t: number) => void }) {
  const visible = events.filter(e => e.code !== 'BUTN').slice(0, 12);
  return <div className="event-list">{visible.length ? visible.map((e, i) => <div key={e.frame + ':' + i}>
    <span className="mono muted">{clock(e.time)}</span>
    {jump ? <button onClick={() => jump(e.time)}>{eventLabels[e.code] ?? e.code}</button>
      : <strong>{eventLabels[e.code] ?? e.code}</strong>}
    {e.details.vehicleIdx != null && <small>CAR {e.details.vehicleIdx + 1}</small>}
    {e.code === 'SCAR' && <small>{e.details.safetyCarType === 2 ? 'VSC' : 'SC'} / {e.details.eventType === 0 ? '導入' : '状態変更'}</small>}
  </div>) : <p className="empty">イベント待ち</p>}</div>;
}

type Marker = { d: number; text: string; color: string };

export function MapView({ snap, selected, large = false, markers = [] }: {
  snap: Snapshot; selected: number; large?: boolean; markers?: Marker[];
}) {
  const track = snap.track;
  const coords = snap.cars.filter(c => c.motion?.worldPositionX != null && c.motion.worldPositionZ != null &&
    (c.motion.worldPositionX !== 0 || c.motion.worldPositionZ !== 0));
  const extents = [...track.map(p => [p[1], p[2]]), ...coords.map(c => [c.motion!.worldPositionX!, c.motion!.worldPositionZ!])];
  const minX = Math.min(...extents.map(p => p[0])), minZ = Math.min(...extents.map(p => p[1]));
  const maxX = Math.max(...extents.map(p => p[0])), maxZ = Math.max(...extents.map(p => p[1]));
  const scale = Math.min(600 / Math.max(1, maxX - minX), 315 / Math.max(1, maxZ - minZ));
  const screen = (x: number, z: number) => [340 + (x - (minX + maxX) / 2) * scale, 185 - (z - (minZ + maxZ) / 2) * scale];
  const trackPath = (predicate: (d: number) => boolean) => {
    let previous = -Infinity;
    return track.map(([d, x, z]) => {
      if (!predicate(d)) { previous = -Infinity; return ''; }
      const point = (d - previous <= 80 ? 'L' : 'M') + screen(x, z).map(v => v.toFixed(1)).join(' ');
      previous = d;
      return point;
    }).join(' ');
  };
  const session = snap.session;
  const length = session?.trackLength ?? 0;
  const zones = (ranges: Zone[]) => trackPath(d => length > 0 && ranges.some(z =>
    z.zoneStart <= z.zoneEnd ? d / length >= z.zoneStart && d / length <= z.zoneEnd :
      d / length >= z.zoneStart || d / length <= z.zoneEnd));
  const active = session?.activeAeroTrackStatus === 1 ? session.activeAeroZonesPartial : session?.activeAeroZonesFull;
  const boundaries = session ? [session.sector2LapDistanceStart, session.sector3LapDistanceStart] : [];
  return <section className={`panel map ${large ? 'large' : ''}`}>
    <div className="panel-head"><div><div className="eyebrow">WORLD POSITION · X / Z</div><h2>サーキットマップ</h2></div>
      <span className="tag">{track.length ? `${track.length} TRACE` : 'TRACE 待ち'}</span></div>
    {extents.length ? <svg viewBox="0 0 680 370" role="img" aria-label="受信した走行位置と走行軌跡">
      <path d={trackPath(() => true)} fill="none" stroke="#4c5c70" strokeWidth="8" strokeLinecap="round" />
      <path d={zones(active ?? [])} fill="none" stroke="#59d7ec" strokeWidth="4" />
      <path d={zones(session?.drsZones ?? [])} fill="none" stroke="#ad9fff" strokeWidth="3" />
      {boundaries.map((d, i) => {
        const p = track.find(v => Math.abs(v[0] - d) <= 15);
        if (!p) return null;
        const [x, y] = screen(p[1], p[2]);
        return <g key={i}><circle cx={x} cy={y} r="7" fill="#f6bf60" />
          <text x={x + 12} y={y - 9} fill="#f6bf60" fontSize="13">S{i + 2}</text></g>;
      })}
      {markers.map(({ d, text, color }, i) => {
        const p = track.reduce<typeof track[number] | null>((best, v) =>
          Math.abs(v[0] - d) < Math.abs((best?.[0] ?? Infinity) - d) ? v : best, null);
        if (!p || Math.abs(p[0] - d) > 35) return null;
        const [x, y] = screen(p[1], p[2]);
        return <circle key={i} cx={x} cy={y} r="6" fill={color} stroke="#0b1017" strokeWidth="2"><title>{text}</title></circle>;
      })}
      {coords.map(c => {
        const [x, y] = screen(c.motion!.worldPositionX!, c.motion!.worldPositionZ!);
        return <g key={c.id}>
          <circle cx={x} cy={y} r={selected === c.id ? 10 : 5}
            fill={selected === c.id ? '#55d6ed' : '#b7c4d3'} stroke="#111923" strokeWidth="2"><title>{carName(c)}</title></circle>
          {selected === c.id && <text x={x + 15} y={y + 4} fill="#55d6ed" fontSize="15">{carName(c)}</text>}
        </g>;
      })}
    </svg> : <div className="map-empty"><span>◎</span><p>走行座標を受信すると描画します</p></div>}
    <div className="readout"><span>走行軌跡</span><span className="accent">アクティブエアロ</span><span className="violet">DRS</span><span className="amber">セクター境界</span>
      {markers.length > 0 && <><span style={{ color: COLORS[2] }}>制動</span><span className="accent">アクセル再開</span><span className="amber">最低速</span><span className="violet">最高速</span></>}</div>
  </section>;
}

export function Circuit({ snap, selected }: { snap: Snapshot; selected: number }) {
  const [all] = useQuery<Lap[]>(snap.run && selected < 24 ? `/api/laps?run=${snap.run}&car=${selected}` : null, 4000);
  const laps = (all ?? []).filter(l => l.epoch === snap.epoch && l.ms && l.valid && (!snap.replay || l.end <= snap.clock));
  const last = laps.at(-1);
  const best = laps.slice(0, -1).reduce<Lap | null>((p, q) => p && p.ms! <= q.ms! ? p : q, null);
  const [comparison] = useQuery<Comparison>(snap.run && last && best
    ? `/api/compare?run=${snap.run}&a=${selected}&b=${selected}&lap_a=${last.lap}&lap_b=${best.lap}&epoch_a=${last.epoch}&epoch_b=${best.epoch}`
    : null);
  const markers: Marker[] = [];
  const pts = comparison?.points.filter(p => p.a?.speed != null) ?? [];
  const fastest = pts.reduce<typeof pts[number] | null>((p, q) => p && p.a!.speed! > q.a!.speed! ? p : q, null);
  if (fastest) markers.push({ d: fastest.d, text: `最高速 ${n(fastest.a?.speed)} km/h`, color: COLORS[3] });
  for (const z of comparison?.zones ?? []) {
    const loss = ` · 区間差 ${n(z.loss, 3)} s`;
    if (z.a.brakeAt != null) markers.push({ d: z.a.brakeAt, text: '制動開始' + loss, color: COLORS[2] });
    if (z.a.throttleAt != null) markers.push({ d: z.a.throttleAt, text: 'アクセル再開' + loss, color: COLORS[0] });
    const low = pts.filter(p => p.d >= z.from && p.d <= z.to)
      .reduce<typeof pts[number] | null>((p, q) => p && p.a!.speed! < q.a!.speed! ? p : q, null);
    if (low) markers.push({ d: low.d, text: `区間最低速 ${n(low.a?.speed)} km/h` + loss, color: COLORS[1] });
  }
  return <><MapView snap={snap} selected={selected} large markers={markers} />
    <section className="panel padded"><h2>走行ライン上の比較</h2>
      {last && best ? <p>L{last.lap} と L{best.lap} · 座標を観測できた区間に解析点を重ねています。</p>
        : <p className="muted">計測地点の比較には、記録済みの有効ラップが2周必要です。</p>}
      {(comparison?.zones ?? []).filter(z => z.loss > 0.03).sort((a, b) => b.loss - a.loss).slice(0, 5).map(z =>
        <p key={z.from}>{n(z.from)}–{n(z.to)} m · +{n(z.loss, 3)} s · {z.hypothesis ?? '制動・最低速・出口を比較'}</p>)}
    </section>
  </>;
}

function useTrace(snap: Snapshot, id: number, limit = 700) {
  const query = snap.run && id < 24 ? `/api/samples?run=${snap.run}&epoch=${snap.epoch}&car=${id}&limit=${limit}${snap.replay ? `&until=${snap.clock}` : ''}` : null;
  return useQuery<Sample[]>(query, snap.replay ? 0 : 1200);
}

export function Driver({ snap, car }: { snap: Snapshot; car: Car | undefined }) {
  const [axis, setAxis] = useState<'time' | 'distance'>('time');
  const [trace, error] = useTrace(snap, car?.id ?? 255);
  const data = useMemo(() => {
    const p = trace ?? [];
    if (axis === 'time') return p;
    let begin = p.length - 1;
    while (begin > 0 && p[begin - 1].d <= p[begin].d) begin--;
    return p.slice(Math.max(0, begin));
  }, [trace, axis]);
  const x = data.map(p => axis === 'time' ? p.t : p.d);
  const t = car?.telemetry, l = car?.lap, s = car?.status;
  return <>
    <div className="metric-grid">
      <Metric label="SPEED" value={n(t?.speed)} hint="km/h" /><Metric label="GEAR" value={n(t?.gear)} />
      <Metric label="ENGINE" value={n(t?.engineRPM)} hint="RPM" /><Metric label="THROTTLE" value={n(t?.throttle == null ? null : t.throttle * 100)} hint="%" />
      <Metric label="BRAKE" value={n(t?.brake == null ? null : t.brake * 100)} hint="%" />
      <Metric label="STEER" value={n(t?.steer, 3)} /><Metric label="LAP DISTANCE" value={n(l?.lapDistance)} hint="m" />
      <Metric label="FUEL" value={n(s?.fuelInTank, 2)} hint="kg" /><Metric label="ENGINE TEMP" value={n(t?.engineTemperature)} hint="°C" />
      <Metric label="ERS STORE" value={n(s?.ersStoreEnergy == null ? null : s.ersStoreEnergy / 1000, 0)} hint="kJ" />
      <Metric label="ENGINE DAMAGE" value={n(car?.damage?.engineDamage)} hint="%" />
      <Metric label="FRONT WING · L / R" value={`${n(car?.damage?.frontLeftWingDamage)} / ${n(car?.damage?.frontRightWingDamage)}`} hint="%" />
    </div>
    <div className="bar"><span>グラフ基準</span><button aria-pressed={axis === 'time'} onClick={() => setAxis('time')}>時刻</button>
      <button aria-pressed={axis === 'distance'} onClick={() => setAxis('distance')}>走行距離</button>
      {error && <span className="amber">{error}</span>}</div>
    <div className="two-col">
      <Chart key={'speed-' + axis} x={x} unit={axis === 'time' ? 's' : 'm'} name="速度 / km/h"
        series={[{ key: 'speed', label: '速度', color: COLORS[0], values: data.map(p => p.speed) }]} />
      <Chart key={'inputs-' + axis} x={x} unit={axis === 'time' ? 's' : 'm'} name="ペダル・ステアリング"
        series={(['throttle', 'brake', 'steer'] as const).map((key, i) =>
          ({ key, label: ['アクセル', 'ブレーキ', 'ステア'][i], color: COLORS[i], values: data.map(p => p[key]) }))} />
      <Chart key={'rpm-' + axis} x={x} unit={axis === 'time' ? 's' : 'm'} name="エンジン回転 / RPM"
        series={[{ key: 'rpm', label: 'RPM', color: COLORS[3], values: data.map(p => p.engineRPM) }]} />
      <Chart key={'gear-' + axis} x={x} unit={axis === 'time' ? 's' : 'm'} name="ギア"
        series={[{ key: 'gear', label: 'ギア', color: COLORS[1], values: data.map(p => p.gear) }]} />
    </div>
    <Tyres snap={snap} car={car} compact />
  </>;
}

const WHEELS = ['左後 / RL', '右後 / RR', '左前 / FL', '右前 / FR'];

export function Tyres({ snap, car, compact = false }: { snap: Snapshot; car: Car | undefined; compact?: boolean }) {
  const [trace] = useTrace(snap, car?.id ?? 255);
  const [tyreLaps] = useQuery<Lap[]>(!compact && snap.run && car ? `/api/laps?run=${snap.run}&car=${car.id}` : null, 2400);
  const [trend, setTrend] = useState<'tyresSurfaceTemperature' | 'tyresWear' | 'tyresInnerTemperature' | 'brakesTemperature' | 'tyresPressure'>('tyresSurfaceTemperature');
  const samples = trace ?? [];
  const lapRows = (tyreLaps ?? []).filter(l => l.epoch === snap.epoch && l.ms && (!snap.replay || l.end <= snap.clock));
  const t = car?.telemetry, d = car?.damage, s = car?.status;
  const model = car?.id === snap.player ? snap.strategy?.model : undefined;
  return <>
    <section className="panel">
      <div className="panel-head"><div><div className="eyebrow">MEASURED · 4 CORNERS</div><h2>タイヤ / ブレーキ</h2></div>
        <span className="tag">{car?.tyre ?? 'N/A'} · {n(s?.tyresAgeLaps)} LAPS</span></div>
      <div className="table-scroll"><table><thead><tr>{['WHEEL', 'SURFACE °C', 'INNER °C', 'BRAKE °C', 'PRESSURE PSI', 'WEAR %'].map(x => <th key={x}>{x}</th>)}</tr></thead>
        <tbody>{WHEELS.map((x, i) => <tr key={x}><td>{x}</td><td>{n(t?.tyresSurfaceTemperature?.[i])}</td>
          <td>{n(t?.tyresInnerTemperature?.[i])}</td><td>{n(t?.brakesTemperature?.[i])}</td>
          <td>{n(t?.tyresPressure?.[i], 2)}</td><td>{n(d?.tyresWear?.[i], 1)}</td></tr>)}</tbody></table></div>
    </section>
    {!compact && <>
      <div className="metric-grid">
        <Metric label="EST · WEAR RATE" value={n(model?.wearRate, 2)} hint="% / lap" />
        <Metric label="EST · DEGRADATION" value={n(model?.degradation, 3)} hint="s / lap" />
        <Metric label="EST · LIFE TO LIMIT" value={n(model?.remaining, 1)} hint={`laps to ${n(model?.wearLimit)}%`} />
        <Metric label="CLEAN LAPS USED" value={n(model?.count)} />
      </div>
      <div className="bar"><label className="field compact">履歴チャンネル<select value={trend} onChange={e => setTrend(e.target.value as typeof trend)}>
        <option value="tyresSurfaceTemperature">表面温度</option><option value="tyresInnerTemperature">内部温度</option>
        <option value="brakesTemperature">ブレーキ温度</option><option value="tyresPressure">空気圧</option>
        <option value="tyresWear">摩耗</option>
      </select></label></div>
      <Chart x={samples.map(p => p.t)} unit="s" name="タイヤ履歴"
        series={WHEELS.map((label, i) => ({ key: label, label, color: COLORS[i], values: samples.map(p => p[trend]?.[i]) }))} />
      <Chart x={lapRows.map(l => l.lap)} unit="L" name="記録ラップタイム / s"
        series={[{ key: 'pace', label: 'ラップタイム', color: COLORS[1],
          values: lapRows.map(l => l.ms! / 1000) }]} />
      <section className="panel"><div className="panel-head"><h2>周回ごとのタイヤとペース</h2></div>
        <div className="table-scroll"><table><thead><tr>{['LAP', 'TYRE ID', 'AGE', 'SURFACE AVG °C', 'TIME', 'CLEAN'].map(x => <th key={x}>{x}</th>)}</tr></thead>
          <tbody>{lapRows.map(l => <tr key={l.lap}><td>{l.lap}</td><td>{n(l.tyre)}</td><td>{n(l.age)}</td>
            <td>{n(l.surfaceMean, 1)}</td><td>{lapTime(l.ms)}</td><td>{l.valid ? 'YES' : 'NO'}</td></tr>)}</tbody></table></div>
      </section>
      <p className="muted">推定は現スティントの観測値と設定した摩耗閾値を使用します。燃料量や交通の影響を分離していません。</p>
    </>}
  </>;
}

export function Power({ snap, car }: { snap: Snapshot; car: Car | undefined }) {
  const [data] = useTrace(snap, car?.id ?? 255);
  const samples = data ?? [], a = car?.aero, s = car?.status, enabled = a?.['2026Regulations'] === 1;
  const yes = (v: number | null | undefined) => v === 1 ? 'YES' : v === 0 ? 'NO' : 'N/A';
  const keys = ['ersStoreEnergy', 'ersDeployedThisLap', 'ersHarvestedThisLapMGUK'] as const;
  return <>
    <div className="metric-grid">
      <Metric label="ACTIVE AERO MODE" value={enabled ? a?.activeAeroMode === 1 ? 'STRAIGHT' : a?.activeAeroMode === 0 ? 'CORNER' : 'N/A' : 'N/A'} />
      <Metric label="AERO AVAILABLE" value={enabled ? yes(a?.activeAeroAvailable) : 'N/A'} />
      <Metric label="AERO NEXT" value={enabled ? n(a?.activeAeroActivationDistance || null) : 'N/A'} hint="m" />
      <Metric label="OVERTAKE ACTIVE" value={enabled ? yes(a?.overtakeActive) : 'N/A'} />
      <Metric label="OVERTAKE AVAILABLE" value={enabled ? yes(a?.overtakeAvailable) : 'N/A'} />
      <Metric label="OVERTAKE NEXT" value={enabled ? n(a?.overtakeActivationDistance || null) : 'N/A'} hint="m" />
      <Metric label="ERS MODE" value={n(s?.ersDeployMode)} /><Metric label="ICE / kW" value={n(s?.enginePowerICE == null ? null : s.enginePowerICE / 1000, 1)} />
      <Metric label="MGU-K / kW" value={n(s?.enginePowerMGUK == null ? null : s.enginePowerMGUK / 1000, 1)} />
    </div>
    <Chart x={samples.map(p => p.t)} unit="s" name="ERS エネルギー / kJ"
      series={keys.map((key, i) => ({ key, label: ['蓄電量', '使用（当周）', 'MGU-K 回収（当周）'][i],
        color: COLORS[i], values: samples.map(p => p[key] == null ? null : p[key]! / 1000) }))} />
    <p className="muted">UDP実測値。次回利用までの距離はパケットのゼロ値を N/A として表示します。</p>
  </>;
}

export function LapComparison({ snap, selected }: { snap: Snapshot; selected: number }) {
  const [rival, setRival] = useState<number | null>(null);
  const b = rival ?? selected;
  const [lapsA] = useQuery<Lap[]>(snap.run && selected < 24 ? `/api/laps?run=${snap.run}&car=${selected}` : null, 2500);
  const [lapsB] = useQuery<Lap[]>(snap.run && b < 24 ? `/api/laps?run=${snap.run}&car=${b}` : null, 2500);
  const [choiceA, setA] = useState('');
  const [choiceB, setB] = useState('');
  const [channel, setChannel] = useState('speed');
  const key = (l: Lap) => `${l.epoch}/${l.lap}`;
  const last = (laps: Lap[] | null) => (laps ?? []).filter(l => (!snap.replay || l.start <= snap.clock) && l.epoch === snap.epoch);
  const aOptions = last(lapsA), bOptions = last(lapsB);
  const complete = bOptions.filter(l => l.ms && l.valid && (!snap.replay || l.end <= snap.clock));
  const best = complete.reduce<Lap | null>((p, q) => p && p.ms! <= q.ms! ? p : q, null);
  const a = aOptions.find(l => key(l) === choiceA) ?? aOptions.at(-1);
  const baseline = bOptions.find(l => key(l) === choiceB) ?? best;
  const [data, error] = useQuery<Comparison>(snap.run && a && baseline
    ? `/api/compare?run=${snap.run}&a=${selected}&b=${b}&lap_a=${a.lap}&lap_b=${baseline.lap}&epoch_a=${a.epoch}&epoch_b=${baseline.epoch}${snap.replay ? `&until=${snap.clock}` : ''}`
    : null, snap.replay ? 0 : 1600);
  const points = data?.points ?? [];
  const channels: Record<string, string> = { speed: '速度 km/h', throttle: 'アクセル', brake: 'ブレーキ', steer: 'ステア', gear: 'ギア', engineRPM: 'RPM' };
  return <>
    <section className="panel padded">
      <div className="bar"><label className="field compact">比較ラップ<select value={choiceA} onChange={e => setA(e.target.value)}>
        <option value="">現在のラップ</option>{aOptions.map(l => <option key={key(l)} value={key(l)}>L{l.lap} · {lapTime(l.ms)}</option>)}
      </select></label>
      <CarSelect cars={snap.cars} selected={b} onSelect={id => { setRival(id); setB(''); }} label="基準ドライバー" />
      <label className="field compact">基準ラップ<select value={choiceB} onChange={e => setB(e.target.value)}>
        <option value="">記録上のベスト</option>{bOptions.map(l => <option key={key(l)} value={key(l)}>L{l.lap} · {lapTime(l.ms)}</option>)}
      </select></label>
      <label className="field compact">チャンネル<select value={channel} onChange={e => setChannel(e.target.value)}>
        {Object.entries(channels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select></label></div>
      <p className="muted">{error ?? data?.reason ?? (a && baseline ? `L${a.lap} vs L${baseline.lap} · 共通点 ${data?.compared ?? '…'}` : '比較には記録中のサンプルと完了ラップが必要です。')}</p>
    </section>
    <div className="two-col">
      <Chart x={points.map(p => p.d)} unit="m" name={channels[channel]} series={[
        { key: 'a', label: '比較ラップ', color: COLORS[0], values: points.map(p => p.a?.[channel]) },
        { key: 'b', label: '基準ラップ', color: COLORS[1], values: points.map(p => p.b?.[channel]) }]} />
      <Chart x={points.map(p => p.d)} unit="m" name="タイムデルタ / s"
        series={[{ key: 'delta', label: '比較 − 基準', color: COLORS[2], values: points.map(p => p.delta) }]} />
    </div>
    <section className="panel"><div className="panel-head"><h2>制動区間の比較</h2><span className="tag">距離補間 5 m</span></div>
      <div className="table-scroll"><table><thead><tr>{['ZONE m', 'LOSS s', 'BRAKE m', 'RELEASE m', 'ENTRY km/h', 'MIN km/h', 'EXIT km/h', 'THROTTLE m', 'MAX BRAKE', 'STEER', 'PEDAL Δ'].map(x => <th key={x}>{x}</th>)}</tr></thead>
        <tbody>{(data?.zones ?? []).map(z => <tr key={z.from}>
          <td>{n(z.from)}–{n(z.to)}</td><td className={z.loss > 0 ? 'amber' : 'accent'}>{n(z.loss, 3)}</td>
          {['brakeAt', 'releaseAt', 'entrySpeed', 'minSpeed', 'exitSpeed', 'throttleAt', 'maxBrake', 'maxSteer', 'throttleVariation'].map((k, i) =>
            <td key={k}>{pair(z.a, z.b, k, i >= 6 ? 2 : 0)}</td>)}</tr>)}</tbody></table></div>
      <div className="padded"><p className="muted">各指標は「比較ラップ / 基準ラップ」。{data?.limits}</p>
        {(data?.zones ?? []).filter(z => z.hypothesis).slice(0, 3).map(z => <p key={z.from}>{n(z.from)} m · {z.hypothesis}</p>)}</div>
    </section>
  </>;
}
function pair(a: Metrics, b: Metrics, k: string, digits: number) {
  return `${n(a[k], digits)} / ${n(b[k], digits)}`;
}
