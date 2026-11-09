const find = id => document.getElementById(id);
const svg = 'http://www.w3.org/2000/svg';
const view = {
  play: find('play'), seek: find('seek'), rate: find('rate'), sc: find('sc'), time: find('time'),
  lap: find('lap'), flag: find('flag'), speed: find('speed'), gear: find('gear'), pedals: find('pedals'),
  cars: find('cars'), markers: find('markers'), recommend: find('recommend'),
  reason: find('reason'), wear: find('wear'), plans: find('plans'), load: find('load'),
  temperature: find('temperature'), ahead: find('ahead'), aheadDriver: find('ahead-driver'), clock: find('clock'),
  previousTrace: find('previous-trace'), currentTrace: find('current-trace'), traceLap: find('trace-lap'),
  selectedCar: find('selected-car'), driver: find('driver-select'), events: find('events'),
};
const number = (value, digits = 0) => value == null ? 'N/A' : value.toFixed(digits);
const clock = t => `${Math.floor(t / 60)}:${Math.floor(t % 60).toString().padStart(2, '0')}`;
function lapTime(ms) {
  if (!ms) return 'N/A';
  return `${clock(ms / 1000)}.${String(ms % 1000).padStart(3, '0')}`;
}
function gap(ms) {
  return ms == null ? 'N/A' : '+' + number(ms / 1000, 3);
}

const cells = new Map();
const markers = new Map();
let race;
let projected;
let events;
let eventCount = -1;
let selected = 1;
let index = 0;
let timer = null;
let gapMode = false;
let recordsByCar;
const teamColors = ['#00d2be', '#ed202b', '#4781d9', '#59b9ed', '#1ea483', '#2685ad', '#647ff5', '#c1c7cc', '#ff880d', '#babfc5', '#c8a460'];
const seconds = ms => number(ms == null ? null : ms / 1000, 3);

function initMap(traces) {
  const points = traces.flat();
  const xs = points.map(row => row[0]);
  const zs = points.map(row => row[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const z0 = Math.min(...zs), z1 = Math.max(...zs);
  const scale = Math.min(595 / (x1 - x0), 305 / (z1 - z0));
  return traces.map(trace => trace.map(([x, z, lap]) => [
    (340 + (x - (x0 + x1) / 2) * scale).toFixed(1),
    (185 - (z - (z0 + z1) / 2) * scale).toFixed(1),
    lap,
  ]));
}

function path(trace, start, end) {
  const points = [];
  for (let i = start; i <= end; i++) {
    const [x, y] = trace[i];
    points.push(`${i === start ? 'M' : 'L'}${x} ${y}`);
  }
  return points.join(' ');
}

function drawTrace(sample) {
  const trace = projected[selected - 1];
  const lap = trace[sample][2];
  let start = sample;
  while (start > 0 && trace[start - 1][2] === lap) start--;
  view.previousTrace.setAttribute('d', start > 0 ? path(trace, 0, start) : '');
  view.currentTrace.setAttribute('d', path(trace, start, sample));
  view.traceLap.textContent = 'LAP ' + lap;
}

const workspaces = {
  'pit-wall': ['PIT WALL', 'ピットウォール'],
  circuit: ['CIRCUIT', 'サーキット'],
  strategy: ['STRATEGY', 'レース戦略'],
  replay: ['REPLAY', 'セッションリプレイ'],
  timing: ['LAP RECORDS', '周回記録'],
  live: ['PS5 LIVE', 'PS5 ライブ接続'],
};
function showWorkspace() {
  const key = location.hash.slice(1);
  const current = Object.hasOwn(workspaces, key) ? key : 'pit-wall';
  const [english, japanese] = workspaces[current];
  find('workspace-label').textContent = 'RACE OPERATIONS / ' + english;
  find('workspace-title').textContent = japanese;
  document.querySelectorAll('nav a').forEach(link => {
    if (link.hash === '#' + current) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  const aside = find('pit-wall-aside');
  const map = find('circuit-panel');
  const strategy = find('strategy-panel');
  const focus = find('focus-panel');
  aside.prepend(map, strategy);
  if (current === 'circuit') focus.append(map);
  if (current === 'strategy') focus.append(strategy);
  const single = current === 'circuit' || current === 'strategy';
  const live = current === 'live';
  const timing = current === 'timing';
  focus.hidden = !single;
  find('pit-wall-grid').hidden = single || live || timing;
  find('timing-panel').hidden = !timing;
  find('replay-controls').hidden = current !== 'replay';
  find('live-panel').hidden = !live;
  find('race-metrics').hidden = live;
  view.driver.parentElement.hidden = live;
  view.play.hidden = live;
  if (timing && recordsByCar) drawTiming(race.frames[index].cars.find(c => c.id === selected));
}
window.addEventListener('hashchange', showWorkspace);
showWorkspace();

function selectDriver(id) {
  selected = id;
  find('timing-lap').value = '';
  view.driver.value = id;
  draw();
}
view.driver.addEventListener('change', () => selectDriver(Number(view.driver.value)));

function makeRow(car) {
  const row = document.createElement('tr');
  const fields = Array.from({ length: 13 }, () => row.insertCell());
  fields[0].className = 'leader-pos';
  const badge = document.createElement('b');
  badge.style.backgroundColor = teamColors[car.teamId - 476] ?? '#64778b';
  fields[0].append(badge);
  const button = document.createElement('button');
  button.className = 'driver';
  button.textContent = 'D' + String(car.id).padStart(2, '0');
  button.setAttribute('aria-label', car.name);
  button.addEventListener('click', () => selectDriver(car.id));
  fields[1].append(button);
  view.cars.append(row);
  view.driver.add(new Option(car.name, car.id));
  const dot = document.createElementNS(svg, 'circle');
  dot.setAttribute('stroke', '#111923');
  dot.setAttribute('stroke-width', '2');
  const title = document.createElementNS(svg, 'title');
  title.textContent = car.name;
  dot.append(title);
  view.markers.append(dot);
  const sectors = fields.slice(6, 9).map(cell => {
    cell.className = 'leader-sector';
    const time = document.createElement('span');
    const rail = document.createElement('div');
    rail.className = 'mini-rail';
    rail.setAttribute('role', 'img');
    rail.append(...Array.from({ length: 10 }, () => document.createElement('span')));
    cell.append(time, rail);
    return { time, rail };
  });
  cells.set(car.id, { row, fields, button, badge, sectors });
  markers.set(car.id, dot);
}

function drawTiming(car) {
  const known = (recordsByCar.get(car.id) ?? []).filter(record => record.lap <= car.lap);
  const picker = find('timing-lap');
  const previous = picker.value;
  const available = known.map(record => String(record.lap)).join(',');
  if (picker.dataset.available !== available) {
    picker.replaceChildren(new Option('現在の周回', ''), ...known.map(record => new Option('L' + record.lap, record.lap)));
    picker.value = known.some(record => String(record.lap) === previous) ? previous : '';
    picker.dataset.available = available;
  }
  const chosen = known.find(record => record.lap === Number(picker.value)) ?? known.at(-1);
  function visibleMini(record, mini) {
    return record.lap < car.lap || (mini.toM <= car.distance && mini.number < 30);
  }
  find('timing-laps').replaceChildren(...known.map(record => {
    const row = document.createElement('tr');
    row.classList.toggle('selected', record === chosen);
    const complete = record.lap < car.lap;
    const sectors = complete ? record.sectors.map(s => s.ms) : [car.sector1, car.sector2, null];
    const count = record.minis.filter(mini => visibleMini(record, mini) && mini.ms != null).length;
    ['L' + record.lap, lapTime(complete ? record.ms : car.elapsed), ...sectors.map(seconds), count + '/' + record.minis.length]
      .forEach(value => { row.insertCell().textContent = value; });
    return row;
  }));
  find('timing-minis').replaceChildren(...[1, 2, 3].map(sector => {
    const column = document.createElement('div');
    column.className = 'mini-record';
    const heading = document.createElement('h3');
    heading.textContent = 'SECTOR ' + sector;
    column.append(heading);
    for (const mini of chosen?.minis.filter(item => item.sector === sector) ?? []) {
      const row = document.createElement('div');
      row.className = 'mini-record-row';
      const time = visibleMini(chosen, mini) ? seconds(mini.ms) : '—';
      row.append(...['M' + String(mini.number).padStart(2, '0'), number(mini.fromM) + '–' + number(mini.toM) + ' m', time]
        .map(value => { const cell = document.createElement('span'); cell.textContent = value; return cell; }));
      column.append(row);
    }
    return column;
  }));
}

find('timing-lap').addEventListener('change', draw);
for (const [id, leaderGap] of [['interval-mode', false], ['gap-mode', true]]) {
  find(id).addEventListener('click', () => {
    gapMode = leaderGap;
    find('interval-mode').setAttribute('aria-pressed', String(!gapMode));
    find('gap-mode').setAttribute('aria-pressed', String(gapMode));
    find('gap-header').textContent = gapMode ? 'GAP' : 'INT';
    if (race) draw();
  });
}

function drawEvents() {
  const visible = events.filter(event => event.index <= index);
  if (visible.length === eventCount) return;
  eventCount = visible.length;
  view.events.replaceChildren(...visible.reverse().map(event => {
    const row = document.createElement('div');
    const time = document.createElement('span');
    time.className = 'mono muted';
    time.textContent = clock(event.time);
    const message = document.createElement('strong');
    message.textContent = event.title;
    row.append(time, message);
    return row;
  }));
}

function draw() {
  const frame = race.frames[index];
  const car = frame.cars.find(c => c.id === selected);
  view.seek.value = index;
  view.time.textContent = `${clock(frame.t)} / ${clock(race.frames.at(-1).t)}`;
  view.clock.textContent = clock(frame.t);
  view.lap.textContent = `${number(frame.lap)} / ${number(frame.total)}`;
  view.flag.textContent = ['GREEN', 'SAFETY CAR', 'VSC', 'FORMATION'][frame.safety] ?? 'N/A';
  view.flag.classList.toggle('amber', frame.safety !== 0);
  view.temperature.textContent = number(frame.temperature);
  view.ahead.textContent = gap(car.gap);
  view.aheadDriver.textContent = car.name;
  view.selectedCar.textContent = car.name;
  view.speed.textContent = number(car.speed) + ' km/h';
  view.gear.textContent = `G${number(car.gear)} · ${number(car.rpm)} RPM`;
  view.pedals.textContent = `THR ${number(car.throttle)}% · BRK ${number(car.brake)}%`;
  drawTrace(frame.sample);
  drawEvents();
  if (location.hash === '#timing') drawTiming(car);
  for (const c of frame.cars) {
    const { row, fields, button, badge, sectors } = cells.get(c.id);
    const chosen = c.id === selected;
    row.classList.toggle('selected', chosen);
    button.setAttribute('aria-pressed', String(chosen));
    badge.textContent = number(c.position);
    const items = [null, null, `${c.tyre ?? '—'} · ${number(c.age)}L`, c.position === 1 ? 'LEAD' : gap(gapMode ? c.leader : c.gap),
      lapTime(c.last), lapTime(c.best), null, null, null, number(c.stops), c.used == null ? '—' : number(c.used) + '%',
      number(c.speed), number(c.energy == null ? null : c.energy / 1e6, 2)];
    items.forEach((text, i) => { if (text !== null) fields[i].textContent = text; });
    const previous = recordsByCar.get(c.id)?.find(record => record.lap === c.lap - 1);
    [c.sector1, c.sector2, previous?.sectors[2].ms].forEach((ms, i) => {
      const { time, rail } = sectors[i];
      const [start, end] = race.sectorBounds.slice(i, i + 2);
      const done = Math.min(10, Math.max(0, Math.floor(10 * (c.distance - start) / (end - start))));
      time.textContent = seconds(ms);
      rail.setAttribute('aria-label', `S${i + 1} ミニセクター ${done}/10 通過`);
      Array.from(rail.children).forEach((child, j) => child.classList.toggle('passed', j < done));
    });
    const [x, y] = projected[c.id - 1][frame.sample];
    const dot = markers.get(c.id);
    dot.setAttribute('cx', x);
    dot.setAttribute('cy', y);
    dot.setAttribute('r', chosen ? '9' : '5');
    dot.setAttribute('fill', chosen ? '#62dded' : '#c0cbd9');
    dot.dataset.selected = String(chosen);
    if (chosen) view.markers.append(dot);
  }
  const model = frame.strategy;
  view.recommend.textContent = '推奨 ' + (model.pick ?? 'N/A');
  view.reason.textContent = model.reason;
  view.wear.textContent = `最大摩耗 ${number(model.wear, 1)}% · 寿命推定 ${number(model.remaining, 1)} 周`;
  const rows = model.plans.map(plan => {
    const row = document.createElement('tr');
    row.classList.toggle('selected', plan.id === model.pick);
    [plan.id, number(plan.lap), number(plan.time, 2), number(plan.loss, 1)].forEach(text => { row.insertCell().textContent = text; });
    return row;
  });
  view.plans.replaceChildren(...rows);
}

function stop() {
  window.clearInterval(timer);
  timer = null;
  view.play.textContent = '再生';
}
function play() {
  if (index === race.frames.length - 1) index = 0;
  draw();
  view.play.textContent = '一時停止';
  timer = window.setInterval(() => {
    index = Math.min(race.frames.length - 1, index + Number(view.rate.value));
    draw();
    if (index === race.frames.length - 1) stop();
  }, 1000 / race.fps);
}
window.addEventListener('hashchange', () => {
  if (location.hash === '#live') stop();
});
view.play.addEventListener('click', () => timer === null ? play() : stop());
view.seek.addEventListener('input', () => { stop(); index = Number(view.seek.value); draw(); });
view.sc.addEventListener('click', () => {
  stop();
  index = race.frames.findIndex(frame => frame.safety === 1);
  draw();
});

try {
  const [data, timing] = await Promise.all(['race.json', 'timing.json'].map(async path => {
    const response = await fetch(`./${path}?v=4`);
    if (!response.ok) throw new Error('HTTP ' + response.status);
    return response.json();
  }));
  race = data;
  if (race.version !== 4 || !race.frames.length || race.traces.length !== 24) throw new Error('invalid demo file');
  recordsByCar = new Map();
  for (const record of timing.laps) {
    const id = record.car + 1;
    if (!recordsByCar.has(id)) recordsByCar.set(id, []);
    recordsByCar.get(id).push(record);
  }
  projected = initMap(race.traces);
  events = race.frames.flatMap((frame, index) => {
    if (index === 0) return [{ index, time: frame.t, title: 'セッション開始' }];
    if (frame.safety === race.frames[index - 1].safety) return [];
    return [{ index, time: frame.t, title: frame.safety === 1 ? 'セーフティカー導入' : 'グリーンフラッグ' }];
  });
  race.frames[0].cars.forEach(makeRow);
  view.driver.value = selected;
  view.driver.disabled = false;
  view.seek.max = race.frames.length - 1;
  view.play.disabled = false;
  view.seek.disabled = false;
  view.sc.disabled = !race.frames.some(frame => frame.safety === 1);
  view.load.hidden = true;
  if (location.hash === '#live' || matchMedia('(prefers-reduced-motion: reduce)').matches) draw();
  else play();
} catch (error) {
  view.load.textContent = 'デモデータを読み込めませんでした。ページを再読み込みしてください。';
  console.error(error);
}
