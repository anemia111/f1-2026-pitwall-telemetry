import { useEffect, useRef, useState } from 'react';
import { clock, n, post, useQuery } from './api';
import type { FormEvent } from 'react';
import type { Assumptions, Radio, Snapshot } from './types';
import { carName, Metric } from './telemetry';

export type RadioSettings = { name: string; frequency: 'Minimal' | 'Standard' | 'Detailed' | 'Coaching'; audio: boolean };
export const defaultRadio: RadioSettings = { name: '裕樹', frequency: 'Standard', audio: false };
const thresholds = { Minimal: 4, Standard: 3, Detailed: 2, Coaching: 1 };
const priorities = { CRITICAL: 4, HIGH: 3, NORMAL: 2, LOW: 1 };

function speak(text: string, interrupt = false): boolean {
  if (!('speechSynthesis' in window)) return false;
  const voice = speechSynthesis.getVoices().find(v => v.localService && v.lang.toLowerCase().startsWith('ja'));
  if (!voice) return false;
  if (speechSynthesis.speaking && !interrupt) return false;
  if (interrupt) speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.voice = voice;
  utterance.lang = voice.lang;
  speechSynthesis.speak(utterance);
  return true;
}

export function useRadio(snap: Snapshot | null, settings: RadioSettings, connected: boolean) {
  const channel = useRef({ key: '', last: 0, speechAt: 0 });
  useEffect(() => {
    if (!connected || !snap?.online || snap.ended || snap.replay || !settings.audio) {
      if ('speechSynthesis' in window) speechSynthesis.cancel();
      channel.current.key = '';
      return;
    }
    const key = snap.uid + ':' + snap.epoch + ':' + snap.source;
    const feed = snap.radio ?? [];
    const last = Math.max(0, ...feed.map(item => item.id ?? 0));
    if (channel.current.key !== key) {
      channel.current = { key, last, speechAt: 0 };
      if ('speechSynthesis' in window) speechSynthesis.cancel();
      return;
    }
    const previous = channel.current.last;
    channel.current.last = Math.max(last, previous);
    const candidate = feed.filter(item => (item.id ?? 0) > previous && snap.clock - item.time <= 3 &&
      item.priority && priorities[item.priority] >= thresholds[settings.frequency])
      .sort((a, b) => priorities[b.priority!] - priorities[a.priority!] || (b.id ?? 0) - (a.id ?? 0))[0];
    if (!candidate?.message || !candidate.priority || (snap.red && candidate.topic !== 'red')) return;
    const critical = candidate.priority === 'CRITICAL';
    const now = performance.now();
    if (!critical && now - channel.current.speechAt < 5000) return;
    if (speak(`${settings.name}、${candidate.message}`, critical)) channel.current.speechAt = now;
  }, [snap, settings, connected]);
}

type LocalRecognition = {
  lang: string; processLocally: boolean; start(): void; abort(): void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
};

function Microphone({ setText, setError, disabled }: {
  setText: (s: string) => void; setError: (s: string) => void; disabled: boolean;
}) {
  const current = useRef<LocalRecognition | null>(null);
  const [listening, setListening] = useState(false);
  useEffect(() => () => current.current?.abort(), []);
  async function listen() {
    const cls = (window as unknown as {
      SpeechRecognition?: { new(): LocalRecognition; available?: (o: { langs: string[]; processLocally: boolean }) => Promise<string> };
    }).SpeechRecognition;
    if (!window.isSecureContext || !cls?.available) {
      setError('このブラウザ環境では端末内の音声認識を使用できません。テキスト入力をご利用ください。');
      return;
    }
    try {
      if (await cls.available({ langs: ['ja-JP'], processLocally: true }) !== 'available') {
        setError('日本語の端末内音声認識が利用できません。テキスト入力をご利用ください。'); return;
      }
      const rec = new cls();
      rec.lang = 'ja-JP'; rec.processLocally = true;
      rec.onresult = e => { const text = e.results[0]?.[0]?.transcript; if (text) setText(text.slice(0, 240)); };
      rec.onerror = e => setError('音声認識: ' + e.error);
      rec.onend = () => { current.current = null; setListening(false); };
      current.current = rec;
      rec.start();
      setListening(true);
    } catch (e) { setError(String(e)); }
  }
  return <button type="button" disabled={disabled} onClick={() => listening ? current.current?.abort() : void listen()}>
    {listening ? '収録停止' : '音声入力'}
  </button>;
}

export function RadioFeed({ items, expanded = false }: { items: Radio[]; expanded?: boolean }) {
  return <div className="radio-list">
    {items.length ? items.slice(0, expanded ? 30 : 6).map((r, i) => <article key={r.id ?? i}>
      <div className="radio-meta"><span className={`priority ${r.priority?.toLowerCase() ?? 'normal'}`}>{r.priority ?? 'LOG'}</span>
        <span>{clock(r.time)}{r.lap ? ` · LAP ${r.lap}` : ''}</span></div>
      <p>{r.message ?? r.reason}</p>
      {expanded && <details><summary>判断根拠・入力データ</summary>
        <p>{r.confidence} · {r.reason}</p><pre>{JSON.stringify(r.evidence, null, 2)}</pre>
        {r.outcome != null && <><p>観測された結果</p><pre>{JSON.stringify(r.outcome, null, 2)}</pre></>}</details>}
    </article>) : <p className="empty">無線メッセージはまだありません。</p>}
  </div>;
}

export function EngineerView({ snap, settings, change, connected }: {
  snap: Snapshot; settings: RadioSettings; change: (s: RadioSettings) => void; connected: boolean;
}) {
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null);
  const fresh = connected && snap.online && !snap.replay && !snap.ended && !snap.red && !snap.session?.gamePaused;
  const generation = useRef('');
  const key = snap.uid + ':' + snap.epoch + ':' + fresh;
  generation.current = key;
  useEffect(() => { setAnswer(''); setError(''); setMetrics(null); }, [key]);

  async function ask(e: FormEvent) {
    e.preventDefault();
    if (!question.trim() || !fresh || busy) return;
    setBusy(true); setError('');
    try {
      const result = await post<{ text: string; llm: Record<string, unknown> | null }>('/api/ask', { text: question.trim() });
      if (key !== generation.current) return;
      setAnswer(result.text);
      setMetrics(result.llm);
      if (settings.audio) speak(result.text);
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  return <>
    <div className="two-col">
      <section className="panel padded"><div className="eyebrow">LOCAL · EVIDENCE BASED</div><h2>AI レースエンジニア</h2>
        <p className={fresh ? 'accent' : 'amber'}>{fresh ? '稼働中' : 'ライブ判断停止中'}</p>
        <div className="bar"><label className="field">呼び名<input maxLength={24} value={settings.name} onChange={e => change({ ...settings, name: e.target.value })} /></label>
          <label className="field">無線頻度<select value={settings.frequency} onChange={e => change({ ...settings, frequency: e.target.value as RadioSettings['frequency'] })}>
            {Object.keys(thresholds).map(k => <option key={k}>{k}</option>)}</select></label>
          <button aria-pressed={settings.audio} onClick={() => {
            const audio = !settings.audio;
            if (audio && !speak('レースエンジニア、接続確認。', true)) setError('端末に日本語のローカル音声がありません。無線はテキストで確認できます。');
            change({ ...settings, audio });
          }}>{settings.audio ? '無線音声 ON' : '無線音声 OFF'}</button></div>
      </section>
      <section className="panel padded"><div className="eyebrow">DRIVER TO ENGINEER</div><h2>ドライバーからの質問</h2>
        <form className="ask" onSubmit={ask}>
          <label className="sr-only" htmlFor="question">レースエンジニアへの質問</label>
          <input id="question" placeholder="前の車とのギャップは？" maxLength={240} value={question} onChange={e => setQuestion(e.target.value)} />
          <button className="primary" disabled={!fresh || busy || !question.trim()}>{busy ? '処理中' : '送信'}</button>
          <Microphone setText={setQuestion} setError={setError} disabled={!fresh} />
        </form>
        {error && <p role="alert" className="amber">{error}</p>}
        {answer && <p role="status" className="answer">{answer}</p>}
        {metrics && <p className="muted">Ollama · {String(metrics.wallMs)} ms{metrics.fallback ? ' · ルール応答へ切替' : ''}</p>}
        <p className="muted">ペース・ギャップ・タイヤ寿命・プランA/B/C・ERS・走行改善</p>
      </section>
    </div>
    <StrategyView snap={snap} />
    <section className="panel"><div className="panel-head"><h2>無線履歴</h2><span className="tag">TEAM RADIO</span></div>
      <RadioFeed items={snap.radio ?? []} expanded /></section>
    <section className="panel padded"><h2>ドライビング改善</h2>
      <p>{snap.coaching ?? '比較可能な走行の記録を待っています。「どこを改善すればいい？」と質問できます。'}</p></section>
  </>;
}

export function StrategyView({ snap }: { snap: Snapshot }) {
  const s = snap.strategy;
  const [status, setStatus] = useState('');
  const [decisionRefresh, bump] = useState(0);
  const [decisions] = useQuery<Radio[]>(snap.run ? `/api/decisions?run=${snap.run}&view=${decisionRefresh}` : null, 4500);
  const [config, setConfig] = useState<Omit<Assumptions, 'simulations'> | null>(null);
  const edit = config ?? s?.assumptions;
  const m = s?.model;
  const revision = snap.revision;
  const who = carName(snap.cars.find(c => c.id === snap.player));
  const names = { A: '基準 1 ストップ', B: '早めに交換', C: 'スティント延長' };
  return <>
    <section className="panel padded">
      <div className="eyebrow">CONDITIONAL MODEL · {who}</div>
      <h2>ピット戦略 A / B / C</h2>
      <p>{s?.reason ?? 'ライブ戦略データ待ち'}</p>
      <div className="metric-grid">
        <Metric label="推奨プラン" value={s?.recommended ?? 'N/A'} />
        <Metric label="交換周回" value={n(s?.plans.find(p => p.id === s.recommended)?.pitLap)} />
        <Metric label="寿命推定 / 周" value={n(m?.remaining, 1)} hint={`摩耗 ${n(m?.wearLimit)}% まで`} />
        <Metric label="最大摩耗 / %" value={n(m?.wear, 1)} />
        <Metric label="比較用有効ラップ" value={n(m?.count)} />
        <Metric label="交換可能セット" value={s?.input.compoundsAvailable.join(' · ') || 'N/A'} />
      </div>
      {revision && <p className="notice">戦略変更 · {revision.previous?.slice(0, 2).join(' / L') ?? '保留'} → {revision.current?.slice(0, 2).join(' / L') ?? '保留'} · {revision.reason}</p>}
    </section>
    <div className="plan-grid">{(['A', 'B', 'C'] as const).map(id => {
      const plan = s?.plans.find(p => p.id === id);
      return <section className={`panel plan ${s?.recommended === id ? 'recommended' : ''}`} key={id}>
        <div className="panel-head"><div><div className="eyebrow">PLAN {id}</div><h3>{names[id]}</h3></div>
          {s?.recommended === id && <span className="tag live">推奨候補</span>}</div>
        <dl><dt>交換周回 / タイヤ</dt><dd>{n(plan?.pitLap)} / {plan?.compound ?? 'N/A'}</dd>
          <dt>予測残り時間</dt><dd>{n(plan?.remainingTime, 2)} s</dd><dt>予測総時間</dt><dd>{n(plan?.raceTime, 2)} s</dd>
          <dt>P10–P90（残り時間）</dt><dd>{plan?.interval ? plan.interval.map(v => n(v, 2)).join('–') + ' s' : 'N/A'}</dd>
          <dt>復帰順位</dt><dd>{n(plan?.rejoin)}</dd><dt>ゴール時最大摩耗</dt><dd>{n(plan?.finishWear, 1)} %</dd>
          <dt>候補内最短の比率</dt><dd>{n(plan?.winRate == null ? null : plan.winRate * 100, 0)} %</dd></dl>
        <p className="muted">{plan?.risk ?? '入力データ待ち'}</p>
        <button disabled={!plan?.pitLap || !snap.online || !!snap.replay || !snap.run} onClick={async () => {
          try { await post('/api/plan', { plan: id }); setStatus(`プラン${id}を手動選択として記録しました。`); bump(v => v + 1); }
          catch (e) { setStatus(String(e)); }
        }}>選択を記録</button>
      </section>;
    })}</div>
    <div className="two-col">
      <section className="panel padded"><h2>前後車両のペース</h2>
        {s?.rivals.length ? s.rivals.map(r => <p key={r.id}>P{r.position} · {r.name ?? `CAR ${r.id + 1}`} · {n(r.pace, 3)} s / lap</p>)
          : <p className="muted">比較できる前後車両の有効ラップがありません。</p>}
        <p className="muted">各車の直近最大3有効ラップの中央値。</p></section>
      <section className="panel padded"><h2>シミュレーション設定</h2>
        {edit && <form className="config-grid" onSubmit={async e => {
          e.preventDefault();
          try {
            const { pit_loss, sc_loss, vsc_loss, wear_limit } = edit;
            await post('/api/config', { pit_loss, sc_loss, vsc_loss, wear_limit });
            setStatus('仮定を更新しました。');
          } catch (e) { setStatus(String(e)); }
        }}>
          {([['pit_loss', 'グリーン ピットロス / s'], ['sc_loss', 'SC ピットロス / s'],
            ['vsc_loss', 'VSC ピットロス / s'], ['wear_limit', '摩耗閾値 / %']] as const).map(([key, label]) =>
            <label className="field" key={key}>{label}<input type="number" min={key === 'wear_limit' ? 1 : 0}
              max={key === 'wear_limit' ? 100 : 180} step=".1" required value={Number.isNaN(edit[key]) ? '' : edit[key]}
              onChange={e => setConfig({ ...edit, [key]: e.target.valueAsNumber })} /></label>)}
          <button disabled={!!snap.replay}>仮定を適用</button>
        </form>}
        <p className="muted">ピットロスはコースごとの設定値。区間はモデル内のばらつきです。</p>
        {status && <p role="status">{status}</p>}
      </section>
    </div>
    <details className="panel padded"><summary>保存済みの判断ログ</summary>
      <RadioFeed items={(decisions ?? []).filter(d => !snap.replay || d.time <= snap.clock)} expanded /></details>
  </>;
}
