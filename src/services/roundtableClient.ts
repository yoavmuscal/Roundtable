import type { CalibrationPayload, ClientMessage, ServerMessage } from '../contract';
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

  connect(): void {
    this.manuallyClosed = false;
    this.openSocket();
  }

  disconnect(): void {
    this.manuallyClosed = true;
    window.clearTimeout(this.reconnectTimer);
    window.clearInterval(this.pingTimer);
    this.socket?.close();
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
    const store = useRoundtableStore.getState();
    store.setConnected(false, 'Connecting to local backend…');
    const socket = new WebSocket(WS_URL);
    this.socket = socket;

    socket.addEventListener('open', () => {
      this.samples = [];
      this.send({ type: 'hello', client: 'roundtable-ui', version: CONTRACT_VERSION });
      useRoundtableStore.getState().setConnected(true, 'Connected locally');
      this.startClockSync();
    });

    socket.addEventListener('message', (event) => {
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
        useRoundtableStore.getState().applyMessage(message);
      } catch (error) {
        console.error('Could not parse backend message', error);
      }
    });

    socket.addEventListener('close', () => {
      window.clearInterval(this.pingTimer);
      useRoundtableStore.getState().setConnected(false, 'Local backend disconnected');
      if (!this.manuallyClosed) {
        this.reconnectTimer = window.setTimeout(() => this.openSocket(), 1200);
      }
    });

    socket.addEventListener('error', () => {
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
