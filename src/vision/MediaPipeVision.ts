import {
  FaceLandmarker,
  FilesetResolver,
  PoseLandmarker,
  type FaceLandmarkerResult,
  type PoseLandmarkerResult,
} from '@mediapipe/tasks-vision';
import type { Box, Point } from '../contract';
import {
  buildAnchors,
  centerOf,
  landmarksBox,
  mouthScore,
  nearestPoseIndex,
  shirtHistogram,
  strictlyIncreasingTimestamp,
  type TimedValue,
} from './math';

export interface VisionObservation {
  faceBox: Box;
  mouth: number;
  jawVariation: number;
  shoulder: Point;
  chest: Point;
  headTop: Point;
  torsoVisible: boolean;
  shirtHistogram: number[];
}

export interface VisionAssets {
  wasmBasePath: string;
  faceModelPath: string;
  poseModelPath: string;
}

export const LOCAL_VISION_ASSETS: VisionAssets = {
  wasmBasePath: '/vision/wasm',
  faceModelPath: '/vision/models/face_landmarker.task',
  poseModelPath: '/vision/models/pose_landmarker_lite.task',
};

export interface BrowserVisionOptions {
  assets?: VisionAssets;
  tableTopY?: number;
  frameIntervalMs?: number;
  onObservations: (observations: VisionObservation[], atSeconds: number) => void;
  onError?: (error: Error) => void;
  /** Camera to open; omitted = prefer a wired iPhone, else the default (laptop) camera. */
  deviceId?: string;
  /** Enrolled headcount. Fewer faces means less GPU work on an 8 GB laptop. */
  numFaces?: number;
}

/** Camera + MediaPipe processor. All model and WASM paths are local app assets. */
export class MediaPipeBrowserVision {
  private faceLandmarker?: FaceLandmarker;
  private poseLandmarker?: PoseLandmarker;
  private stream?: MediaStream;
  private animationFrame?: number;
  private lastVideoTimestamp?: number;
  private lastEmitMs = 0;
  private faceTurn = true;
  private lastFaces?: FaceLandmarkerResult;
  private lastPoses?: PoseLandmarkerResult;
  private jawHistories: TimedValue[][] = [];
  private jawCenters: Point[] = [];
  private histogramCanvas: HTMLCanvasElement;
  private histogramContext: CanvasRenderingContext2D;

  constructor(private readonly options: BrowserVisionOptions) {
    this.histogramCanvas = document.createElement('canvas');
    this.histogramCanvas.width = 160;
    this.histogramCanvas.height = 90;
    const context = this.histogramCanvas.getContext('2d', { willReadFrequently: true });
    if (!context) throw new Error('Could not create a canvas for shirt-color histograms');
    this.histogramContext = context;
  }

  async start(video: HTMLVideoElement): Promise<void> {
    const assets = this.options.assets ?? LOCAL_VISION_ASSETS;
    const fileset = await FilesetResolver.forVisionTasks(assets.wasmBasePath);
    this.faceLandmarker = await FaceLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: assets.faceModelPath, delegate: 'GPU' },
      runningMode: 'VIDEO',
      numFaces: this.options.numFaces ?? 3,
      minFaceDetectionConfidence: 0.55,
      minFacePresenceConfidence: 0.55,
      minTrackingConfidence: 0.6,
      outputFaceBlendshapes: true,
    });
    this.poseLandmarker = await PoseLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: assets.poseModelPath, delegate: 'GPU' },
      runningMode: 'VIDEO',
      numPoses: this.options.numFaces ?? 3,
      minPoseDetectionConfidence: 0.55,
      minTrackingConfidence: 0.6,
    });
    if (!video.srcObject) {
      this.stream = await openPreferredCamera(this.options.deviceId);
      video.srcObject = this.stream;
      await video.play();
    }
    const intervalMs = Math.max(50, this.options.frameIntervalMs ?? 100);
    const tick = () => {
      try {
        this.process(video);
      } catch (error) {
        this.options.onError?.(error instanceof Error ? error : new Error(String(error)));
      }
    };
    tick();
    this.animationFrame = window.setInterval(tick, intervalMs);
  }

  stop(): void {
    if (this.animationFrame !== undefined) window.clearInterval(this.animationFrame);
    this.stream?.getTracks().forEach((track) => track.stop());
    this.faceLandmarker?.close();
    this.poseLandmarker?.close();
    this.faceLandmarker = undefined;
    this.poseLandmarker = undefined;
    this.lastFaces = undefined;
    this.lastPoses = undefined;
    this.jawHistories = [];
    this.jawCenters = [];
  }

  /** Alternates face/pose inference and emits combined observations at ~10/s. */
  process(video: HTMLVideoElement): void {
    if (!this.faceLandmarker || !this.poseLandmarker || video.readyState < 2) return;
    const nowMs = performance.now();
    if (nowMs - this.lastEmitMs < (this.options.frameIntervalMs ?? 100)) return;
    this.lastEmitMs = nowMs;
    const timestamp = strictlyIncreasingTimestamp(this.lastVideoTimestamp, Math.round(video.currentTime * 1000));
    this.lastVideoTimestamp = timestamp;

    if (this.faceTurn) {
      this.lastFaces = this.faceLandmarker.detectForVideo(video, timestamp);
    } else {
      this.lastPoses = this.poseLandmarker.detectForVideo(video, timestamp);
    }
    this.faceTurn = !this.faceTurn;

    const faces = this.lastFaces?.faceLandmarks ?? [];
    const poses = (this.lastPoses?.landmarks ?? []).map((pose) => pose.map(({ x, y }) => ({ x, y })));
    if (!faces.length) {
      this.jawHistories = [];
      this.jawCenters = [];
      this.options.onObservations([], video.currentTime);
      return;
    }
    this.drawHistogramFrame(video);
    const imageData = this.histogramContext.getImageData(0, 0, this.histogramCanvas.width, this.histogramCanvas.height);
    const observations = faces.slice(0, 4).map((landmarks, index) => {
      const faceBox = landmarksBox(landmarks);
      const poseIndex = nearestPoseIndex(faceBox, poses);
      const pose = poseIndex === undefined ? undefined : poses[poseIndex];
      const anchors = buildAnchors(faceBox, pose, this.options.tableTopY);
      const jawOpen = this.lastFaces?.faceBlendshapes[index]?.categories.find(
        (category) => category.categoryName === 'jawOpen',
      )?.score ?? 0;
      const historySlot = this.historySlot(centerOf(faceBox));
      this.jawHistories[historySlot].push({ time: video.currentTime, value: jawOpen });
      this.jawHistories[historySlot] = this.jawHistories[historySlot].filter(
        (sample) => video.currentTime - sample.time <= 0.6,
      );
      const score = mouthScore(this.jawHistories[historySlot], video.currentTime);
      const shoulder = pose?.[11] && pose[12]
        ? { x: (pose[11].x + pose[12].x) / 2, y: (pose[11].y + pose[12].y) / 2 }
        : { x: faceBox.x + faceBox.width / 2, y: faceBox.y + faceBox.height * 1.15 };
      return {
        faceBox,
        mouth: score,
        jawVariation: score * 0.08,
        shoulder,
        chest: anchors.chest,
        headTop: anchors.headTop,
        torsoVisible: anchors.torsoVisible,
        shirtHistogram: shirtHistogram(
          imageData.data,
          imageData.width,
          imageData.height,
          shirtBox(faceBox, shoulder),
        ),
      } satisfies VisionObservation;
    });
    this.options.onObservations(observations, video.currentTime);
  }

  private historySlot(center: Point): number {
    let best = -1;
    let bestDistance = Number.POSITIVE_INFINITY;
    this.jawCenters.forEach((existing, index) => {
      const distance = Math.hypot(existing.x - center.x, existing.y - center.y);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = index;
      }
    });
    if (best >= 0 && bestDistance <= 0.15) {
      this.jawCenters[best] = center;
      return best;
    }
    if (this.jawCenters.length < 4) {
      this.jawCenters.push(center);
      this.jawHistories.push([]);
      return this.jawCenters.length - 1;
    }
    this.jawCenters[0] = center;
    this.jawHistories[0] = [];
    return 0;
  }

  private drawHistogramFrame(video: HTMLVideoElement): void {
    this.histogramContext.drawImage(
      video,
      0,
      0,
      this.histogramCanvas.width,
      this.histogramCanvas.height,
    );
  }
}

/** Video inputs with labels (labels appear only after camera permission is granted). */
export async function listCameras(): Promise<MediaDeviceInfo[]> {
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.filter((device) => device.kind === 'videoinput');
}

export async function openPreferredCamera(deviceId?: string): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new DOMException('This browser cannot open cameras on this page.', 'NotSupportedError');
  }
  // Ask once so the browser exposes camera labels, then honour the picker or prefer a wired iPhone.
  const permissionStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
  permissionStream.getTracks().forEach((track) => track.stop());
  const cameras = await listCameras();
  const chosen = deviceId ? cameras.find((device) => device.deviceId === deviceId) : undefined;
  const iphone = cameras.find((device) => /iphone/i.test(device.label));
  const target = chosen ?? iphone;
  const constraints: MediaStreamConstraints = {
    video: {
      deviceId: target ? { exact: target.deviceId } : undefined,
      width: { ideal: 1280 },
      height: { ideal: 720 },
      frameRate: { ideal: 30 },
    },
    audio: false,
  };
  return navigator.mediaDevices.getUserMedia(constraints);
}

function shirtBox(face: Box, shoulder: Point): Box {
  const width = Math.min(1, face.width * 2.2);
  const x = Math.max(0, Math.min(1 - width, shoulder.x - width / 2));
  const y = Math.max(0, Math.min(0.95, shoulder.y + face.height * 0.05));
  return {
    x,
    y,
    width,
    height: Math.max(0.02, Math.min(0.98 - y, face.height * 1.7)),
  };
}
