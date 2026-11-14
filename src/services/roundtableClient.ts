import type { CalibrationPayload, ClientMessage, Phase, ServerMessage } from '../contract';
import { CONTRACT_VERSION } from '../contract';
import { estimateClockOffset, type ClockSample } from '../lib/clockSync';
import { useRoundtableStore } from '../state/store';

const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`;

class RoundtableClient {
  private socket?: WebSocket;
  private pingTimer?: number;
  private reconnectTimer?: number;
  private samples: ClockSample[] = [];
  private manuallyClosed = false;
  private connectionGeneration = 0;
  private handshakePending = false;
  /** Screen requested in the URL; wins over the backend's remembered phase on connect. */
  pinnedPhase?: Phase;

  connect(): void {
    if (
      this.socket &&
      (this.socket.readyState === WebSocket.CONNECTING || this.socket.readyState === WebSocket.OPEN)
    ) {
      return;
    }
    this.manuallyClosed = false;
    this.openSocket();
  }

  disconnect(): void {
    this.manuallyClosed = true;
    window.clearTimeout(this.reconnectTimer);
    window.clearInterval(this.pingTimer);
    const socket = this.socket;
    this.socket = undefined;
    socket?.close();
  }

  send(message: ClientMessage): boolean {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(message));
    return true;
  }

  calibrate(payload: CalibrationPayload): boolean {
    return this.send({ type: 'calibrate', payload });
  }

  control(action: Extract<ClientMessage, { type: 'control' }>['action'], value?: string): boolean {
    return this.send({ type: 'control', action, value });
  }

  ask(text: string): boolean {
    return this.send({ type: 'ask', text });
  }

  seatDrag(personId: string, mapPosition: { x: number; y: number }): boolean {
    return this.send({ type: 'seat-drag', personId, mapPosition });
  }

  private openSocket(): void {
    const generation = ++this.connectionGeneration;
    const store = useRoundtableStore.getState();
    store.setConnected(false, 'Connecting to local backend…');
    const socket = new WebSocket(WS_URL);
    this.socket = socket;

    socket.addEventListener('open', () => {
      if (generation !== this.connectionGeneration) return;
      this.samples = [];
      this.handshakePending = true;
      this.send({ type: 'hello', client: 'roundtable-ui', version: CONTRACT_VERSION });
      useRoundtableStore.getState().setConnected(true, 'Connected locally');
      this.startClockSync();
    });

    socket.addEventListener('message', (event) => {
      if (generation !== this.connectionGeneration) return;
      try {
        const message = JSON.parse(event.data as string) as ServerMessage;
        if (message.type === 'pong') {
          const sentAt = Number(message.nonce.split(':')[0]);
          this.samples.push({ sentAt, receivedAt: performance.now() / 1000, backendTime: message.backendTime });
          if (this.samples.length >= 5) {
            useRoundtableStore.getState().setClockOffset(estimateClockOffset(this.samples));
          }
          return;
        }
        if (this.handshakePending && message.type === 'phase') {
          // The hello reply carries the backend's remembered phase. A fresh page load
          // honours the URL's screen, and never drops the user straight into an old Review.
          const store = useRoundtableStore.getState();
          const pinned = this.pinnedPhase;
          this.pinnedPhase = undefined;
          const phase = pinned ?? (message.phase === 'review' && !store.refined ? 'setup' : message.phase);
          store.setPhase(phase);
          return;
        }
        if (this.handshakePending && message.type === 'status') this.handshakePending = false;
        useRoundtableStore.getState().applyMessage(message);
      } catch (error) {
        console.error('Could not parse backend message', error);
      }
    });

    socket.addEventListener('close', () => {
      if (generation !== this.connectionGeneration) return;
      window.clearInterval(this.pingTimer);
      useRoundtableStore.getState().setConnected(false, 'Local backend disconnected');
      if (!this.manuallyClosed) {
        this.reconnectTimer = window.setTimeout(() => this.openSocket(), 1200);
      }
    });

    socket.addEventListener('error', () => {
      if (generation !== this.connectionGeneration) return;
      useRoundtableStore.getState().setConnected(false, 'Cannot reach local backend on :8000');
    });
  }

  private startClockSync(): void {
    window.clearInterval(this.pingTimer);
    let count = 0;
    this.pingTimer = window.setInterval(() => {
      count += 1;
      const now = performance.now() / 1000;
      this.send({ type: 'ping', nonce: `${now}:${count}`, sentAt: now });
      if (count >= 5) window.clearInterval(this.pingTimer);
    }, 120);
  }
}

export const roundtableClient = new RoundtableClient();
