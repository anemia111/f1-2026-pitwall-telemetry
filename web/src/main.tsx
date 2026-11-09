import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { clock, lapTime, n, post, request, useQuery } from './api';
import { defaultRadio, EngineerView, RadioFeed, StrategyView, useRadio } from './radio';
import type { RadioSettings } from './radio';
import { carName, CarSelect, Circuit, Driver, EventList, flag, LapComparison, MapView, Metric, Power, pos, split, Timing, Tyres } from './telemetry';
import type { Lap, Network, Run, Snapshot } from './types';


const TABS = [
  ['wall', 'PIT WALL', 'ピットウォール'], ['ai', 'AI ENGINEER', 'レースエンジニア'],
  ['driver', 'DRIVER', 'ドライバーテレメトリー'], ['compare', 'LAP COMPARE', 'ラップ比較'],
  ['map', 'CIRCUIT', 'サーキット'], ['tyres', 'TYRES', 'タイヤ分析'], ['power', 'POWER UNIT', 'パワーユニット / エアロ'],
  ['strategy', 'STRATEGY', 'レース戦略'], ['replay', 'REPLAY', 'セッションリプレイ'], ['setup', 'CONNECTION', '接続と診断'],
] as const;
type Tab = typeof TABS[number][0];
const currentTab = () => TABS.find(([key]) => key === location.hash.slice(1))?.[0] ?? 'wall';
const blank: Snapshot = { source: 'LIVE', run: null, uid: null, epoch: 0, player: 255, online: false,
  age: null, clock: 0, session: null, cars: [], events: [], track: [], ended: false, red: false, counts: {} };

function loadRadio(): RadioSettings {
  try {
    const s = JSON.parse(sessionStorage.getItem('apex-radio') ?? '{}');
    if (typeof s.name === 'string' && ['Minimal', 'Standard', 'Detailed', 'Coaching'].includes(s.frequency))
      return { name: s.name, frequency: s.frequency, audio: false };
  } catch { /* preferences are optional */ }
  return defaultRadio;
}

function App() {
  const [tab, setTab] = useState<Tab>(currentTab);
  const [live, setLive] = useState<Snapshot | null>(null);
  const [replay, setReplay] = useState<Snapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [login, setLogin] = useState(false);
  const [loginVersion, reconnect] = useState(0);
  const [key, setKey] = useState('');
  const [error, setError] = useState('');
  const [selection, select] = useState<{ uid: string | null; id: number } | null>(null);
  const [radio, setRadio] = useState<RadioSettings>(loadRadio);
  const liveNow = !connected && live ? { ...live, online: false, strategy: undefined, cars: [], session: null } : live;
  const snap = replay ?? liveNow ?? blank;
  const selected = selection?.uid === snap.uid ? selection.id : snap.player;
  const car = snap.cars.find(c => c.id === selected);
  const changeCar = (id: number) => select({ uid: snap.uid, id });
  const pageTitle = TABS.find(([t]) => t === tab)![2];
  useRadio(replay ? null : live, radio, connected);

  useEffect(() => {
    const changed = () => setTab(currentTab());
    window.addEventListener('hashchange', changed);
    return () => window.removeEventListener('hashchange', changed);
  }, []);

  useEffect(() => {
    let ws: WebSocket | undefined;
    let stopped = false;
    let retry: number | undefined;
    let heartbeat: number | undefined;
    async function connect() {
      try {
        const check = await fetch('/api/state');
        if (stopped) return;
        if (check.status === 401) { setLogin(true); return; }
        if (!check.ok) throw new Error('HTTP ' + check.status);
        setLogin(false);
        ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
        ws.onmessage = e => {
          try {
            const s = JSON.parse(e.data) as Snapshot;
            if (!Array.isArray(s.cars)) return;
            setLive(s);
            setConnected(true);
            clearTimeout(heartbeat);
            heartbeat = window.setTimeout(() => ws?.close(), 3500);
          } catch { ws?.close(); }
        };
        ws.onclose = () => {
          clearTimeout(heartbeat);
          setConnected(false);
          if (!stopped) retry = window.setTimeout(connect, 1000);
        };
        ws.onerror = () => ws?.close();
      } catch {
        setConnected(false);
        if (!stopped) retry = window.setTimeout(connect, 1500);
      }
    }
    void connect();
    return () => {
      stopped = true;
      clearTimeout(retry); clearTimeout(heartbeat);
      if (ws) { ws.onclose = null; ws.close(); }
    };
  }, [loginVersion]);

  const changeRadio = (next: RadioSettings) => {
    setRadio(next);
    try { sessionStorage.setItem('apex-radio', JSON.stringify(next)); } catch { /* optional */ }
  };

  if (login) return <main className="login">
    <section className="panel padded"><div className="eyebrow">APEX RACE ENGINEERING</div><h1>2026 PIT WALL</h1>
      <p>LAN アクセスキーを入力してください。</p>
      <form className="field" onSubmit={async e => {
        e.preventDefault();
        try { await post('/api/login', { key }); setKey(''); setError(''); reconnect(v => v + 1); }
        catch (e) { setError(String(e)); }
      }}>
        <label htmlFor="lan-key">アクセスキー</label><input id="lan-key" type="password" required value={key} onChange={e => setKey(e.target.value)} />
        <button className="primary">接続</button>
      </form>{error && <p role="alert">{error}</p>}</section>
  </main>;

  return <>
    <header className="top">
      <a href="#wall" className="brand"><span className="mark">A</span><span><b>APEX</b><small>RACE ENGINEERING</small></span></a>
      <div className="product">2026 <strong>PIT WALL</strong></div>
      <div className="statusbar">
        {snap.replay && <button className="tag demo" onClick={() => { location.hash = 'wall'; setReplay(null); }}>REPLAY 終了</button>}
        <span className={`tag ${snap.source === 'DEMO' ? 'demo' : 'live'}`}>{snap.source === 'DEMO' ? 'DEMO / 模擬データ' : 'LIVE / 実機入力'}</span>
        <span className={`tag ${connected && live?.online ? 'live' : 'offline'}`}><i />{connected && live?.online ? 'UDP 2026' : connected ? 'UDP 待機' : '再接続中'}</span>
        <span className="tag frame">24 CARS</span>
      </div>
    </header>
    <nav aria-label="ワークスペース">{TABS.map(([id, title]) =>
      <a href={'#' + id} key={id} aria-current={tab === id ? 'page' : undefined}>{title}</a>)}</nav>
    <main>
      <div className="page-head"><div><div className="eyebrow">{snap.replay ? 'ARCHIVE / REPLAY' : 'RACE OPERATIONS'} / {TABS.find(([t]) => t === tab)![1]}</div>
        <h1>{pageTitle}</h1></div>
        <div className="page-controls">
          {!['ai', 'strategy', 'setup', 'replay'].includes(tab) && <CarSelect cars={snap.cars} selected={selected} onSelect={changeCar} />}
          {tab !== 'setup' && <a className="button detach" href={'#' + tab} target="_blank" rel="noopener">別ウィンドウ ↗</a>}
        </div></div>
      {snap.source === 'DEMO' && <div className="demo-strip">DEMO SESSION <span>24台の合成UDPデータ · ゲーム内時間は8倍速</span></div>}
      {snap.replay && <div className="replay-strip">REPLAY · {clock(snap.clock)} · アーカイブ表示
        {tab !== 'replay' && <a href="#replay">再生操作へ</a>}</div>}
      {!connected && <div className="notice" role="status">サーバーへ再接続中です。無線を停止しています。</div>}
      {tab === 'wall' && <>
        <div className="metric-grid hero">
          <Metric label="CIRCUIT" value={snap.session?.trackName ?? (snap.source === 'DEMO' ? 'DEMO COURSE' : 'N/A')} hint={`${n(snap.session?.trackLength)} m`} />
          <Metric label="RACE CONTROL" value={flag(snap)} hint={snap.ended ? 'セッション終了' : 'フラッグ状態'} />
          <Metric label="SESSION LAP" value={`${n(snap.cars.find(c => pos(c) === 1)?.lap?.currentLapNum)} / ${n(snap.session?.totalLaps || null)}`} />
          <Metric label="TRACK TEMP" value={n(snap.session?.trackTemperature)} hint="°C" />
          <Metric label="AHEAD" value={split(car?.lap?.frontGap)} hint={carName(car)} />
          <Metric label="RECORDING" value={snap.replay ? 'REPLAY' : snap.connection?.recording ? 'ARMED' : 'OFF'} hint={clock(snap.clock)} />
        </div>
        <div className="wall"><Timing snap={snap} selected={selected} select={changeCar} />
          <aside>
            <MapView snap={snap} selected={selected} />
            <section className="panel"><div className="panel-head"><div><div className="eyebrow">LOCAL AI ENGINEER</div><h2>チーム無線</h2></div>
              <a className="button" href="#ai">開く</a></div><RadioFeed items={snap.radio ?? []} /></section>
            <section className="panel"><div className="panel-head"><h2>レースコントロール</h2><span className="tag">{flag(snap)}</span></div>
              <EventList events={snap.events} /></section>
          </aside>
        </div>
      </>}
      {tab === 'driver' && <Driver snap={snap} car={car} />}
      {tab === 'compare' && <LapComparison key={snap.run ?? 'none'} snap={snap} selected={selected} />}
      {tab === 'map' && <Circuit snap={snap} selected={selected} />}
      {tab === 'tyres' && <Tyres snap={snap} car={car} />}
      {tab === 'power' && <Power snap={snap} car={car} />}
      {tab === 'ai' && <EngineerView snap={snap} settings={radio} change={changeRadio} connected={connected} />}
      {tab === 'strategy' && <StrategyView snap={snap} />}
      {tab === 'replay' && <Replay snap={snap} live={live} active={replay} setReplay={setReplay} selected={selected} select={changeCar} />}
      {tab === 'setup' && <Connection snap={liveNow ?? blank} />}
    </main>
    <footer><span>APEX RACE ENGINEERING</span><span>LOCAL TELEMETRY · F1 25 / 2026 SEASON PACK</span></footer>
  </>;
}

function Replay({ snap, live, active, setReplay, selected, select }: {
  snap: Snapshot; live: Snapshot | null; active: Snapshot | null; setReplay: (v: Snapshot | null) => void;
  selected: number; select: (id: number) => void;
}) {
  const [runs, error] = useQuery<Run[]>('/api/runs', 3000);
  const [id, setId] = useState<string | null>(active?.run ?? null);
  const [at, seek] = useState(active?.clock ?? 0);
  const [play, setPlay] = useState(false);
  const [rate, setRate] = useState(1);
  const [note, setNote] = useState('');
  const [runEnabled, enable] = useState(!!active);
  const run = runs?.find(r => r.id === id);
  const duration = run?.duration ?? 0;
  const [events] = useQuery<Snapshot['events']>(id ? `/api/events?run=${id}` : null, 3000);
  const [laps] = useQuery<Lap[]>(id && active && active.player < 24 ? `/api/laps?run=${id}&car=${active.player}` : null, 3000);

  useEffect(() => {
    if (!play) return;
    let previous = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now(), delta = (now - previous) * rate / 1000;
      previous = now;
      seek(v => Math.min(duration, v + delta));
    }, 250);
    return () => window.clearInterval(timer);
  }, [play, duration, rate]);

  useEffect(() => {
    if (!id || !runEnabled) return;
    const ctl = new AbortController();
    const delay = window.setTimeout(async () => {
      try {
        const s = await request<Snapshot>(`/api/replay?run=${id}&t=${at}`, { signal: ctl.signal });
        if (!ctl.signal.aborted) setReplay(s);
      } catch (e) { if (!ctl.signal.aborted) setNote(String(e)); }
    }, 55);
    return () => { clearTimeout(delay); ctl.abort(); };
  }, [id, at, runEnabled, setReplay]);
  useEffect(() => { if (at >= duration) setPlay(false); }, [at, duration]);
  useEffect(() => {
    if (!active && runEnabled && !id) { setPlay(false); enable(false); }
  }, [active, runEnabled, id]);

  function jump(t: number) { setPlay(false); seek(t); enable(true); }
  return <>
    <section className="panel padded">
      <div className="eyebrow">SQLITE / UDP ARCHIVE</div><h2>保存済みセッション</h2>
      <div className="bar">
        <label className="field compact">セッション<select value={id ?? ''} onChange={e => {
          setId(e.target.value || null); seek(0); enable(!!e.target.value); setReplay(null); setPlay(false);
        }}><option value="">選択してください</option>{(runs ?? []).map(r =>
          <option key={r.id} value={r.id}>{r.source} · {new Date(r.started * 1000).toLocaleString('ja-JP')} · {clock(r.duration)}</option>)}</select></label>
        <button onClick={async () => {
          try {
            const enabled = !live?.connection?.recording;
            await post(`/api/record?enabled=${enabled}`); setNote(enabled ? '自動記録を有効にしました。' : '記録を停止しました。');
          } catch (e) { setNote(String(e)); }
        }}>{live?.connection?.recording ? '記録停止' : '記録開始'}</button>
        {id && (['csv', 'parquet', 'udp'] as const).map(format => <a className="button" key={format} download
          href={`/api/export?run=${id}&format=${format}`}>{format.toUpperCase()}</a>)}
      </div>
      {(error || note) && <p role="status">{error ?? note}</p>}
      {run && <>
        <div className="transport"><button className="primary" onClick={() => {
          if (!play && at >= duration) seek(0);
          enable(true); setPlay(v => !v);
        }}>{play ? '一時停止' : '再生'}</button>
          <label className="field compact">再生速度<select value={rate} onChange={e => setRate(Number(e.target.value))}>
            {[.25, .5, 1, 2, 4].map(r => <option key={r} value={r}>{r}×</option>)}</select></label>
          <input type="range" aria-label="再生位置" min={0} max={Math.max(duration, .01)} step=".05" value={at} onChange={e => jump(e.target.valueAsNumber)} />
          <span className="mono">{clock(at)} / {clock(duration)}</span>
          <button onClick={() => { setPlay(false); enable(false); setReplay(null); setId(null); }}>ライブに戻る</button>
        </div>
      </>}
    </section>
    {id && <div className="two-col">
      <section className="panel"><div className="panel-head"><h2>イベントへジャンプ</h2></div><EventList events={events ?? []} jump={jump} /></section>
      <section className="panel"><div className="panel-head"><h2>ラップへジャンプ</h2></div>
        <div className="event-list">{(laps ?? []).map(l => <div key={l.epoch + ':' + l.lap}>
          <span className="mono">L{l.lap}</span><button onClick={() => jump(l.start)}>{lapTime(l.ms)}</button><small>{l.samples} SAMPLES</small>
        </div>)}</div></section>
    </div>}
    {active && <Timing snap={snap} selected={selected} select={id => { select(id); location.hash = 'driver'; }} />}
  </>;
}

function Connection({ snap }: { snap: Snapshot }) {
  const [info, error] = useQuery<Network>('/api/network', 6000);
  const [target, choose] = useState('');
  const address = target || info?.addresses[0];
  const link = address && info ? `http://${address}:${info.httpPort}/` : null;
  const c = snap.connection;
  return <>
    <div className="metric-grid">
      <Metric label="UDP FORMAT" value="2026" /><Metric label="UDP PORT" value={n(info?.udpPort)} />
      <Metric label="SOURCE IP" value={c?.sender ?? 'N/A'} /><Metric label="LAST RX" value={n(snap.age, 2)} hint="s ago" />
      <Metric label="VALID" value={n(snap.counts.valid)} /><Metric label="INVALID" value={n(snap.counts.invalid)} />
      <Metric label="IGNORED / LATE" value={`${n(snap.counts.ignored)} / ${n(snap.counts.late)}`} />
      <Metric label="FRAME ID GAPS" value={n(snap.counts.frameGaps)} hint="参考値 · 実損失率ではない" />
      <Metric label="RX PROCESS PEAK" value={n(c?.peakMs, 2)} hint="ms / 直近120件" />
      <Metric label="ARCHIVE QUEUE / DROPS" value={`${n(c?.archiveQueue)} / ${n(c?.archiveDrops)}`} />
    </div>
    <div className="two-col">
      <section className="panel padded"><h2>PS5 接続</h2>
        <ol><li>PC と PS5 を同じ LAN に接続します。</li>
          <li>ゲームの UDP Telemetry を ON。送信先を下記 PC の IPv4 に設定します。</li>
          <li>ポート {n(info?.udpPort)}、UDP Format 2026、送信レート 60 Hz。</li>
          <li>Windows ファイアウォールのプライベートネットワークで UDP を許可します。</li></ol>
        <p className="mono">PC IPv4 · {info?.addresses.join(' / ') || 'N/A'}</p>
        <p className="muted">最終パーサーエラー {c?.error ?? '—'}</p>
        {c?.archiveError && <p role="alert" className="amber">{c.archiveError}</p>}
        {error && <p role="alert">{error}</p>}
      </section>
      <section className="panel padded"><h2>スマートフォン / タブレット</h2>
        {info?.lan && link ? <>
          <label className="field compact">PC アドレス<select value={address} onChange={e => choose(e.target.value)}>
            {info.addresses.map(ip => <option key={ip}>{ip}</option>)}</select></label>
          <p><a href={link}>{link}</a></p>
          <img className="qr" width="164" height="164" alt="同じLANのブラウザでピットウォールを開くQRコード"
            src={`/api/qr?host=${address}&port=${info.httpPort}`} />
        </> : <p>LAN 接続は無効です。起動時に <code>-Lan</code> とアクセスキーを設定してください。</p>}
        <p className="muted">Ollama · {info?.ollama ? 'ローカルモデル設定済み' : 'ルールベース応答'}</p>
      </section>
    </div>
  </>;
}

createRoot(document.getElementById('root')!).render(<App />);
