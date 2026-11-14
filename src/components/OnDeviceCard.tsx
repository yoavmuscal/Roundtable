import { useRoundtableStore } from '../state/store';

export function OnDeviceCard() {
  const status = useRoundtableStore((state) => state.status);
  const connected = useRoundtableStore((state) => state.connected);
  const ram = typeof status.ramGb === 'number' && status.ramGb > 0 ? status.ramGb : undefined;
  const perTurn = typeof status.secondsPerTurn === 'number' && status.secondsPerTurn > 0 ? status.secondsPerTurn : undefined;
  const bonsaiOffline = /offline/i.test(status.model);
  const healthy = connected && status.network === 'none' && (ram ?? 0) < 7 && !bonsaiOffline;

  return (
    <section className={healthy ? 'on-device card ok' : 'on-device card warn'} aria-label="On-device status">
      <div className="card-heading plain-heading">
        <strong>On device</strong>
      </div>
      <div className="device-lines">
        <p className={bonsaiOffline ? 'device-warn' : undefined}>
          {status.model || 'Bonsai 2 2B'}{perTurn ? ` · ${perTurn.toFixed(1)} s/turn` : ''}
        </p>
        <p>WhisperKit · SpeakerKit{status.backend === 'simulation' ? ' (replay)' : ''}</p>
        <p>RAM {ram ? ram.toFixed(1) : '—'} / 8 GB</p>
        <p className="network-line"><span /> {connected ? `Network: ${status.network}` : 'Backend offline'}</p>
      </div>
    </section>
  );
}
