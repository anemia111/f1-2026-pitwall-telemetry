const find = id => document.getElementById(id);
const svg = 'http://www.w3.org/2000/svg';
const view = {
  play: find('play'), seek: find('seek'), rate: find('rate'), sc: find('sc'), time: find('time'),
  lap: find('lap'), flag: find('flag'), speed: find('speed'), gear: find('gear'), pedals: find('pedals'),
  cars: find('cars'), track: find('track'), markers: find('markers'), recommend: find('recommend'),
  reason: find('reason'), wear: find('wear'), plans: find('plans'), load: find('load'),
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
let project;
let selected = 1;
let index = 0;
let timer = null;

function initMap(track) {
  const xs = track.map(row => row[1]);
  const zs = track.map(row => row[2]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const z0 = Math.min(...zs), z1 = Math.max(...zs);
  const scale = Math.min(595 / (x1 - x0), 305 / (z1 - z0));
  project = (x, z) => [340 + (x - (x0 + x1) / 2) * scale, 185 - (z - (z0 + z1) / 2) * scale];
  const path = track.map(([, x, z], i) => `${i ? 'L' : 'M'}${project(x, z).map(v => v.toFixed(1)).join(' ')}`);
  view.track.setAttribute('d', path.join(' ') + ' Z');
}

function makeRow(car) {
  const row = document.createElement('tr');
  const fields = Array.from({ length: 9 }, () => row.insertCell());
  fields[0].className = 'position';
  const button = document.createElement('button');
  button.className = 'driver';
  button.textContent = car.name;
  button.addEventListener('click', () => { selected = car.id; draw(); });
  fields[1].append(button);
  view.cars.append(row);
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

function draw() {
  const frame = race.frames[index];
  const car = frame.cars.find(c => c.id === selected);
  view.seek.value = index;
  view.time.textContent = `${clock(frame.t)} / ${clock(race.frames.at(-1).t)}`;
  view.lap.textContent = `${number(frame.lap)} / ${number(frame.total)}`;
  view.flag.textContent = ['GREEN', 'SAFETY CAR', 'VSC', 'FORMATION'][frame.safety] ?? 'N/A';
  view.flag.classList.toggle('amber', frame.safety !== 0);
  view.speed.textContent = number(car.speed);
  view.gear.textContent = `${number(car.gear)} / ${number(car.rpm)}`;
  view.pedals.textContent = `${number(car.throttle)}% / ${number(car.brake)}%`;
  for (const c of frame.cars) {
    const { row, fields, button } = cells.get(c.id);
    const chosen = c.id === selected;
    row.classList.toggle('selected', chosen);
    button.setAttribute('aria-pressed', String(chosen));
    const items = [number(c.position), null, c.tyre ?? 'N/A', number(c.lap), lapTime(c.best), lapTime(c.last),
      gap(c.gap), c.position === 1 ? 'LEAD' : gap(c.leader), c.aero === 1 ? 'STR' : c.aero === 0 ? 'COR' : 'N/A'];
    items.forEach((text, i) => { if (text !== null) fields[i].textContent = text; });
    const [x, y] = project(c.x, c.z);
    const dot = markers.get(c.id);
    dot.setAttribute('cx', x);
    dot.setAttribute('cy', y);
    dot.setAttribute('r', chosen ? '9' : '5');
    dot.setAttribute('fill', chosen ? '#62dded' : '#c0cbd9');
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
  const response = await fetch('./race.json');
  if (!response.ok) throw new Error('HTTP ' + response.status);
  race = await response.json();
  if (race.version !== 1 || !race.frames.length || !race.track.length) throw new Error('invalid demo file');
  initMap(race.track);
  race.frames[0].cars.forEach(makeRow);
  view.seek.max = race.frames.length - 1;
  view.play.disabled = false;
  view.seek.disabled = false;
  view.sc.disabled = !race.frames.some(frame => frame.safety === 1);
  view.load.textContent = '再生、シーク、車両選択、セーフティカー導入時点へのジャンプができます。';
  draw();
} catch (error) {
  view.load.textContent = 'デモデータを読み込めませんでした。ページを再読み込みしてください。';
  console.error(error);
}
