export type Metrics = Record<string, number | null | undefined>;
export type Sample = {
  t: number; d: number; ms: number; speed: number; rpm?: number; engineRPM: number; gear: number;
  throttle: number; brake: number; steer: number; valid: boolean;
  tyresSurfaceTemperature?: (number | null)[]; tyresInnerTemperature?: (number | null)[];
  brakesTemperature?: (number | null)[]; tyresPressure?: (number | null)[]; tyresWear?: (number | null)[];
  ersStoreEnergy?: number; ersDeployedThisLap?: number; ersHarvestedThisLapMGUK?: number; fuelInTank?: number;
  worldPositionX?: number; worldPositionZ?: number;
};
export type Car = {
  id: number; name: string | null; team: string | null; best: number | null; tyre: string | null;
  participant: { raceNumber: number; teamId: number } | null;
  lap: Metrics | null; status: Metrics | null; aero: Metrics | null; result: Metrics | null;
  motion: Metrics | null; telemetry: (Partial<Sample> & { engineTemperature?: number }) | null;
  damage: (Partial<Sample> & { engineDamage?: number; frontLeftWingDamage?: number; frontRightWingDamage?: number }) | null;
};
export type Zone = { zoneStart: number; zoneEnd: number };
export type Session = {
  trackName: string | null; trackLength: number; sessionType: number; totalLaps: number; safetyCarStatus: number;
  weather: number; trackTemperature: number; airTemperature: number; gamePaused: number; isSpectating: number;
  sector2LapDistanceStart: number; sector3LapDistanceStart: number; activeAeroTrackStatus: number;
  activeAeroZonesFull: Zone[]; activeAeroZonesPartial: Zone[]; drsZones: Zone[];
  pitStopWindowIdealLap: number; pitStopWindowLatestLap: number; pitStopRejoinPosition: number;
};
export type Plan = {
  id: 'A' | 'B' | 'C'; pitLap: number | null; remainingTime: number | null; raceTime: number | null;
  rejoin: number | null; interval: [number, number] | null; finishWear: number | null; winRate: number | null;
  pitLoss?: number; compound?: string; risk: string;
};
export type Assumptions = { pit_loss: number; sc_loss: number; vsc_loss: number; wear_limit: number; simulations: number };
export type Strategy = {
  model: { compound: string | null; age: number | null; wear: number | null; wearRate: number | null;
    remaining: number | null; degradation: number | null; pace: number | null; count: number; wearLimit: number;
    wearPoints: [number, number][] };
  plans: Plan[]; recommended: Plan['id'] | null; reason: string; assumptions: Assumptions;
  rivals: { name: string | null; id: number; position: number; pace: number | null }[];
  input: { compoundsAvailable: string[]; lap?: number };
};
export type Event = { code: string; time: number; frame: number; details: Record<string, number | null> };
export type Radio = { id?: number; priority?: 'CRITICAL' | 'HIGH' | 'NORMAL' | 'LOW'; message?: string; topic: string;
  time: number; lap: number | null; reason: string; evidence: Record<string, unknown>; confidence: string;
  selectedPlan: Plan['id'] | null; outcome?: unknown };
export type Snapshot = {
  source: 'LIVE' | 'DEMO'; replay?: boolean; run: string | null; uid: string | null; epoch: number; player: number;
  online: boolean; age: number | null; clock: number; session: Session | null; cars: Car[]; events: Event[];
  track: [number, number, number][]; ended: boolean; red: boolean; counts: Record<string, number>;
  radio?: Radio[]; strategy?: Strategy; coaching?: string | null;
  revision?: { previous: [string, number, number] | null; current: [string, number, number] | null; reason: string };
  connection?: { port: number; sender: string | null; error: string | null; recording: boolean;
    archiveDrops: number; archiveError: string | null; archiveQueue: number; processMs: number; peakMs: number };
};
export type Run = { id: string; uid: string; source: 'LIVE' | 'DEMO'; started: number; duration: number };
export type Lap = { lap: number; epoch: number; ms: number | null; samples: number; start: number; end: number;
  lastDistance: number; valid: boolean; tyre: number | null; age: number | null; surfaceMean: number | null };
export type Comparison = {
  points: { d: number; a: Metrics | null; b: Metrics | null; delta: number | null }[];
  zones: { from: number; to: number; loss: number; a: Metrics; b: Metrics; hypothesis: string | null }[];
  reason: string | null; limits?: string; compared?: number;
};
export type Network = { addresses: string[]; httpPort: number; udpPort: number; lan: boolean; source: string; ollama: boolean };
