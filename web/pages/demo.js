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
  focus.hidden = !single;
  find('pit-wall-grid').hidden = single;
  find('replay-controls').hidden = current !== 'replay';
}
window.addEventListener('hashchange', showWorkspace);
showWorkspace();

function selectDriver(id) {
  selected = id;
  view.driver.value = id;
  draw();
}
view.driver.addEventListener('change', () => selectDriver(Number(view.driver.value)));

function makeRow(car) {
  const row = document.createElement('tr');
  const fields = Array.from({ length: 15 }, () => row.insertCell());
  fields[0].className = 'position';
  const button = document.createElement('button');
  button.className = 'driver';
  button.textContent = car.name;
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
  cells.set(car.id, { row, fields, button });
  markers.set(car.id, dot);
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
  for (const c of frame.cars) {
    const { row, fields, button } = cells.get(c.id);
    const chosen = c.id === selected;
    row.classList.toggle('selected', chosen);
    button.setAttribute('aria-pressed', String(chosen));
    const status = c.status === 3 ? 'FIN' : c.status === 4 || c.status === 7 ? 'DNF' : c.pit ? 'PIT'
      : c.penalties ? `+${c.penalties}s PEN` : c.status === 2 ? 'TRACK' : 'N/A';
    const items = [number(c.position), null, c.tyre ?? 'N/A', number(c.age), number(c.lap),
      lapTime(c.best), lapTime(c.last), number(c.sector1 == null ? null : c.sector1 / 1000, 3),
      number(c.sector2 == null ? null : c.sector2 / 1000, 3), gap(c.gap), gap(c.behind),
      c.position === 1 ? 'LEAD' : gap(c.leader), status, c.aero === 1 ? 'STR' : c.aero === 0 ? 'COR' : 'N/A',
      c.overtake ? 'ON' : c.overtakeAvailable ? 'RDY' : 'OFF'];
    items.forEach((text, i) => { if (text !== null) fields[i].textContent = text; });
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
view.play.addEventListener('click', () => timer === null ? play() : stop());
view.seek.addEventListener('input', () => { stop(); index = Number(view.seek.value); draw(); });
view.sc.addEventListener('click', () => {
  stop();
  index = race.frames.findIndex(frame => frame.safety === 1);
  draw();
});

try {
  const response = await fetch('./race.json?v=2');
  if (!response.ok) throw new Error('HTTP ' + response.status);
  race = await response.json();
  if (race.version !== 2 || !race.frames.length || race.traces.length !== 24) throw new Error('invalid demo file');
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
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) draw();
  else play();
} catch (error) {
  view.load.textContent = 'デモデータを読み込めませんでした。ページを再読み込みしてください。';
  console.error(error);
}
