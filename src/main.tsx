import { LOCAL_VISION_ASSETS } from './vision/MediaPipeVision';

const root = document.getElementById('root');
if (root) {
  root.innerHTML = `
    <main style="font-family: system-ui; background: #10141B; color: #E6E8EC; min-height: 100vh; display: grid; place-items: center; margin: 0">
      <section>
        <h1>Roundtable backend branch</h1>
        <p>Offline browser vision assets are ready at ${LOCAL_VISION_ASSETS.wasmBasePath}.</p>
        <p>Run <code>npm run backend</code> for the simulation API. Merge the UI branch for the full interface.</p>
      </section>
    </main>`;
}
