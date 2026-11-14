import { useRoundtableStore } from '../state/store';

export function OnDeviceCard() {
  const status = useRoundtableStore((state) => state.status);
  const connected = useRoundtableStore((state) => state.connected);
  const healthy = connected && status.network === 'none' && status.ramGb < 7;

  return (
    <section className={healthy ? 'on-device card ok' : 'on-device card warn'} aria-label="On-device status">
      <div className="card-heading">
        <strong>On-device</strong>
        <span className="status-dot" aria-hidden="true" />
      </div>
      <dl>
        <div>
          <dt>Model</dt>
          <dd>{status.model}</dd>
        </div>
        <div>
          <dt>Latency</dt>
          <dd>{status.secondsPerTurn ? `${status.secondsPerTurn.toFixed(1)} s/turn` : '—'}</dd>
        </div>
        <div>
          <dt>RAM</dt>
          <dd>{status.ramGb ? `${status.ramGb.toFixed(1)} GB` : '—'}</dd>
        </div>
        <div>
          <dt>Network</dt>
          <dd>{status.network === 'none' ? 'none' : 'detected'}</dd>
        </div>
      </dl>
    </section>
  );
}
