import { useState } from 'react';
import { lapTime, n, seconds, useQuery } from './api';
import { carName, pos, split } from './telemetry';
import type { Car, Run, Session, Snapshot, TimingRank } from './types';

const MINI_COUNT = 10;
const RANK_LABEL = { overall: '全体ベスト', personal: '自己ベスト', other: 'その他' };
const TEAMS: Record<number, string> = {
  476: '#00d2be', 477: '#ed202b', 478: '#4781d9', 479: '#59b9ed',
  480: '#1ea483', 481: '#2685ad', 482: '#647ff5', 483: '#c1c7cc',
  484: '#ff880d', 485: '#babfc5', 486: '#c8a460',
};

function sectorBounds(session: Session | null) {
  if (!session) return null;
  const { sector2LapDistanceStart: s2, sector3LapDistanceStart: s3, trackLength } = session;
  return 0 < s2 && s2 < s3 && s3 < trackLength ? [0, s2, s3, trackLength] : null;
}

function driverCode(car: Car) {
  const name = carName(car);
  const surname = name.trim().split(/\s+/).at(-1);
  return surname && /\p{L}/u.test(surname) ? Array.from(surname).slice(0, 3).join('').toUpperCase()
    : car.participant?.raceNumber ? '#' + car.participant.raceNumber : name;
}

function TimingLegend() {
  return <span className="timing-legend" aria-label="タイムの色分け">
    <span className="rank-overall">全体ベスト</span>
    <span className="rank-personal">自己ベスト</span>
    <span className="rank-other">その他</span>
  </span>;
}

function SectorCell({ ms, complete, sector, rank, minis }: {
  ms: number | null | undefined; complete: number | null; sector: number;
  rank?: TimingRank | null; minis?: (TimingRank | null)[];
}) {
  const description = [sector === 3 && ms ? '前周のS3' : '', rank ? RANK_LABEL[rank] : ''].filter(Boolean).join(' · ');
  return <td className="leader-sector">
    <span className={rank ? `rank-${rank}` : undefined} title={description || undefined}>{ms ? seconds(ms) : '—'}</span>
    <div className="mini-rail" role="img" aria-label={complete == null ? `S${sector} ミニセクター進捗不明` : `S${sector} ミニセクター ${complete}/10 通過`}>
      {Array.from({ length: MINI_COUNT }, (_, i) => {
        const miniRank = minis?.[i];
        const passed = complete != null && i < complete;
        return <span key={i} className={miniRank ? `rank-${miniRank}` : passed ? 'passed' : undefined}
          title={miniRank ? `M${(sector - 1) * MINI_COUNT + i + 1} · ${RANK_LABEL[miniRank]}` : undefined} />;
      })}
    </div>
  </td>;
}

export function RaceLeaderboard({ snap, selected, select }: {
  snap: Snapshot; selected: number; select: (id: number) => void;
}) {
  const [mode, setMode] = useState<'live' | 'gap'>('live');
  const gates = sectorBounds(snap.session);
  return <section className="panel race-leaderboard timing">
    <header className="leader-head">
      <h2>RACE LEADERBOARD</h2>
      <div className="controls" aria-label="ギャップ表示">
        <button aria-pressed={mode === 'live'} onClick={() => setMode('live')} title="前車との差">LIVE</button>
        <button aria-pressed={mode === 'gap'} onClick={() => setMode('gap')} title="首位との差">GAP</button>
      </div>
    </header>
    <div className="table-scroll" tabIndex={0} aria-label="順位表">
      <table><thead><tr>
        {['POS', 'DRIVER', 'TYRE', mode === 'live' ? 'INT' : 'GAP', 'LAST', 'BEST',
          'S1', 'S2', 'S3', 'ST', 'USED', 'SPD', 'ERS'].map(label => <th scope="col" key={label}>{label}</th>)}
      </tr></thead><tbody>
        {snap.cars.map(car => {
          const l = car.lap, d = l?.lapDistance;
          const position = pos(car);
          const wear = car.damage?.tyresWear?.filter((x): x is number => x != null && x >= 0 && x <= 100);
          const used = wear?.length === 4 ? Math.max(...wear) : null;
          const energy = car.status?.ersStoreEnergy;
          const team = TEAMS[car.participant?.teamId ?? -1] ?? '#64778b';
          const segments = [l?.sector1, l?.sector2, l?.previousSector3];
          return <tr key={car.id} className={selected === car.id ? 'selected' : undefined}>
            <td className="leader-pos"><b style={{ backgroundColor: team }}>{position ?? '—'}</b></td>
            <td><button className="driver" title={carName(car)} aria-label={carName(car)} aria-pressed={selected === car.id}
              onClick={() => select(car.id)}><b>{driverCode(car)}</b></button></td>
            <td><span className="leader-tyre"><span className={`compound tyre-${car.tyre ?? 'none'}`}>{car.tyre ?? '—'}</span>
              <small>{l && car.status?.tyresAgeLaps != null ? n(car.status.tyresAgeLaps) + 'L' : '—'}</small></span></td>
            <td className="leader-time">{position === 1 ? 'LEAD' : split(mode === 'live' ? l?.frontGap : l?.leaderGap)}</td>
            <td className="leader-time">{lapTime(l?.lastLapTimeInMS)}</td>
            <td className="leader-time violet">{lapTime(car.best)}</td>
            {segments.map((ms, i) => {
              const done = d != null && d >= 0 && gates
                ? Math.min(MINI_COUNT, Math.max(0, Math.floor(MINI_COUNT * (d - gates[i]) / (gates[i + 1] - gates[i])))) : null;
              return <SectorCell key={i} ms={ms} complete={done} sector={i + 1}
                rank={car.timingRanks?.sectors[i]} minis={car.timingRanks?.minis.slice(i * MINI_COUNT, (i + 1) * MINI_COUNT)} />;
            })}
            <td title="ピットストップ回数">{n(l?.numPitStops ?? car.result?.numPitStops)}</td>
            <td title="4輪で最大のタイヤ摩耗率">{used == null ? '—' : `${n(used)}%`}</td>
            <td title="km/h">{n(car.telemetry?.speed)}</td>
            <td title="ERS残量（MJ）">{energy == null ? '—' : `${n(energy / 1e6, 2)}`}</td>
          </tr>;
        })}
      </tbody></table>
    </div>
    {!snap.cars.length && <p className="empty">UDP 2026 の順位データを待っています。</p>}
    <div className="leader-footer"><span>{snap.cars.length} / 24 CARS</span><TimingLegend />
      <span>バーは当周 · S3は前周 · ERSはMJ</span><a href="#timing">周回記録 ↗</a></div>
  </section>;
}

type TimingLap = {
  epoch: number; car: number; lap: number; start: number | null; end: number | null; ms: number | null;
  valid: boolean | null;
  sectors: { ms: number | null; source: 'game' | 'difference' | null; valid: boolean | null; rank?: TimingRank | null }[];
  minis: { number: number; sector: number; fromM: number; toM: number; ms: number | null; rank?: TimingRank | null }[];
};
type TimingReport = { run: string; miniSectorsPerSector: number; laps: TimingLap[] };
const lapKey = (lap: TimingLap) => lap.epoch + ':' + lap.lap;

export function LapRecords({ snap, selected }: { snap: Snapshot; selected: number }) {
  const [runs] = useQuery<Run[]>('/api/runs', 3000);
  const [archive, setArchive] = useState<string | null>(null);
  const [driver, setDriver] = useState<number | null>(null);
  const [lapId, setLapId] = useState<string | null>(null);
  const [revision, refresh] = useState(0);
  const run = archive ?? snap.run ?? runs?.[0]?.id;
  const car = driver ?? (selected < 24 ? selected : 0);
  const live = !!run && run === snap.run && !snap.replay && snap.online && !snap.ended && snap.connection?.recording === true;
  const [report, error] = useQuery<TimingReport>(run ? `/api/timing?run=${run}&car=${car}&revision=${revision}` : null, live ? 1000 : 0);
  const laps = report?.laps ?? [];
  const current = live ? snap.cars.find(c => c.id === car)?.lap : null;
  const isCurrent = (row: TimingLap) => !!current && row.epoch === snap.epoch && row.lap === current.currentLapNum;
  const lap = laps.find(l => lapKey(l) === lapId) ?? laps.find(isCurrent) ?? [...laps].reverse().find(l => l.ms != null) ?? laps.at(-1);
  const nameFor = (i: number) => run === snap.run ? snap.cars.find(c => c.id === i)?.name : null;
  return <>
    <section className="panel padded">
      <div className="eyebrow">{live ? 'LIVE TIMING' : 'RECORDED TIMING'} / UDP 2026</div><h2>周回・セクター記録</h2>
      <div className="bar">
        <label className="field compact">セッション<select value={run ?? ''} onChange={e => { setArchive(e.target.value); setLapId(null); }}>
          {!run && <option value="">記録なし</option>}
          {run && !(runs ?? []).some(r => r.id === run) && <option value={run}>現在のセッション</option>}
          {(runs ?? []).map(r => <option value={r.id} key={r.id}>{r.source} · {new Date(r.started * 1000).toLocaleString('ja-JP')}</option>)}
        </select></label>
        <label className="field compact">車両<select value={car} onChange={e => { setDriver(Number(e.target.value)); setLapId(null); }}>
          {Array.from({ length: 24 }, (_, i) => <option value={i} key={i}>CAR {i + 1}{nameFor(i) ? ' · ' + nameFor(i) : ''}</option>)}
        </select></label>
        {live ? <span className="tag live">自動更新中</span> : <button disabled={!run} onClick={() => refresh(v => v + 1)}>最新の記録を読み込む</button>}
        {run && <a className="button" download href={`/api/timing/export?run=${run}`}>全車両の記録 JSON</a>}
      </div>
      <p className="muted timing-note">S1〜S3はゲームのタイムを優先。各セクターを距離で10分割し、通過時刻の差から計算します。</p>
      <TimingLegend />
      {error ? <p className="empty" role="alert">{error}</p>
        : run && !report ? <p className="empty" role="status">保存済みUDPを読み込み中…</p>
        : !laps.length && <p className="empty">選択した車両の周回記録はありません。</p>}
    </section>
    {!!laps.length && <section className="panel">
      <div className="panel-head"><h2>周回一覧</h2><span className="tag">{laps.length} LAPS</span></div>
      <div className="table-scroll"><table><thead><tr>
        {['LAP', 'TIME', 'S1', 'S2', 'S3', 'MINIS', 'VALID', 'EPOCH'].map(x => <th scope="col" key={x}>{x}</th>)}
      </tr></thead><tbody>{laps.map(row => <tr key={lapKey(row)} className={lap === row ? 'selected' : undefined}>
        <td><button aria-pressed={lap === row} onClick={() => setLapId(lapKey(row))}>L{row.lap}</button></td>
        <td>{isCurrent(row) && row.ms == null ? <span className="accent">{lapTime(current?.currentLapTimeInMS)} · 走行中</span> : lapTime(row.ms)}</td>{row.sectors.map((s, i) => <td key={i}
          className={s.rank ? `rank-${s.rank}` : undefined} title={[s.rank ? RANK_LABEL[s.rank] : '',
            s.source === 'difference' ? 'ラップタイムからS1・S2を差し引いた値' : ''].filter(Boolean).join(' · ') || undefined}>
          {seconds(s.ms)}{s.source === 'difference' ? '*' : ''}{s.valid === false && s.ms != null ? ' · 無効' : ''}</td>)}
        <td>{row.minis.length ? `${row.minis.filter(m => m.ms != null).length}/${row.minis.length}` : 'N/A'}</td>
        <td>{row.valid === true ? '有効' : row.valid === false ? '無効' : '未確認'}</td><td>{row.epoch}</td>
      </tr>)}</tbody></table></div>
      <div className="readout">* はラップタイム − S1 − S2。フラッシュバック前後の記録は EPOCH で区別します。</div>
    </section>}
    {lap && <section className="panel">
      <div className="panel-head"><h2>L{lap.lap} · ミニセクター</h2><span className="tag">EPOCH {lap.epoch}</span></div>
      {!lap.minis.length ? <p className="empty">トラック長とセクター境界が取得できていません。</p> :
        <div className="mini-records">{[1, 2, 3].map(sector => <div key={sector} className="mini-record">
          <h3>SECTOR {sector}</h3>
          {lap.minis.filter(m => m.sector === sector).map(m => <div className="mini-record-row" key={m.number}>
            <span>M{String(m.number).padStart(2, '0')}</span><span>{n(m.fromM)}–{n(m.toM)} m</span>
            <strong className={m.rank ? `rank-${m.rank}` : undefined} title={m.rank ? RANK_LABEL[m.rank] : undefined}>
              {m.ms == null ? '欠測' : seconds(m.ms) + ' s'}
            </strong>
          </div>)}
        </div>)}</div>}
    </section>}
  </>;
}

