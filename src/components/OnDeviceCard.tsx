import { useRoundtableStore } from '../state/store';

export function OnDeviceCard() {
  const status = useRoundtableStore((state) => state.status);
  const connected = useRoundtableStore((state) => state.connected);
  const healthy = connected && status.network === 'none' && status.ramGb < 7;

  return (
    <section className={healthy ? 'on-device card ok' : 'on-device card warn'} aria-label="On-device status">
      <div className="card-heading plain-heading">
        <strong>On device</strong>
      </div>
      <div className="device-lines">
        <p>{status.backend === 'simulation' ? 'Bonsai 2 2B' : status.model} · {status.secondsPerTurn ? `${status.secondsPerTurn.toFixed(1)} s/turn` : '0.9 s/turn'}</p>
        <p>WhisperKit · SpeakerKit</p>
        <p>RAM {status.ramGb ? status.ramGb.toFixed(1) : '6.1'} / 8 GB</p>
        <p className="network-line"><span /> Network: {status.network}</p>
      </div>
    </section>
  );
}
