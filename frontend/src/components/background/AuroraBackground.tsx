import { useEffect, useRef } from "react";
import * as THREE from "three";

/**
 * Full-viewport, fixed, non-interactive backdrop: a near-black field with
 * slow gold aurora ribbons drifting through it, plus a sparse layer of
 * floating embers. Pure decoration — `pointer-events-none` throughout,
 * sits behind the UI via z-index, and carries no text or semantics.
 *
 * Deliberately *dark*: the readable UI sits on top of this, so the
 * backdrop stays mostly black and lets gold appear only as thin, soft
 * ribbons. A bright full-screen gradient competes with the foreground and
 * makes body text hard to read.
 *
 * Owns the whole Three.js lifecycle imperatively in one `useEffect`
 * rather than via a React-Three-Fiber-style render loop: this is a single
 * static scene with no interactivity and no React state to sync, so a
 * plain imperative setup/animate/dispose is simpler than wiring up a
 * declarative renderer for it.
 */
export function AuroraBackground(): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Decorative only: WebGL (and even `matchMedia`) isn't guaranteed in
    // every environment this renders in (older devices, test/CI runners
    // like jsdom) — degrade to no background rather than crashing the page.
    let cleanup = (): void => {};
    try {
      cleanup = setupScene(container);
    } catch {
      return;
    }
    return cleanup;
  }, []);

  return (
    <div ref={containerRef} aria-hidden="true" className="pointer-events-none fixed inset-0 -z-10" />
  );
}

function setupScene(container: HTMLDivElement): () => void {
  const prefersReducedMotion =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  container.appendChild(renderer.domElement);

  // Concretely-typed uniforms object (rather than reading back through
  // `material.uniforms.x`, whose type is a plain index signature) so
  // TypeScript knows these keys always exist.
  const uniforms = {
    uTime: { value: 0 },
    uResolution: { value: new THREE.Vector2(window.innerWidth, window.innerHeight) },
  };

  const gradientMaterial = new THREE.ShaderMaterial({
    uniforms,
    vertexShader: `
      varying vec2 vUv;
      void main() {
        vUv = uv;
        gl_Position = vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      varying vec2 vUv;
      uniform float uTime;
      uniform vec2 uResolution;

      /* One soft horizontal ribbon of light: a band whose vertical centre
         wanders with a couple of offset sine waves, falling off smoothly
         so it reads as a glow rather than a hard stripe. */
      float ribbon(vec2 p, float t, float yBase, float amp, float freq, float thickness) {
        float centre = yBase
          + sin(p.x * freq + t) * amp
          + sin(p.x * freq * 0.47 - t * 0.73) * amp * 0.55;
        float d = abs(p.y - centre);
        return smoothstep(thickness, 0.0, d);
      }

      void main() {
        vec2 uv = vUv;
        float aspect = uResolution.x / uResolution.y;
        vec2 p = vec2(uv.x * aspect, uv.y);
        float t = uTime * 0.08;

        /* Base: deep navy-slate, lifting slightly toward indigo at the
           bottom so the page doesn't read as a flat void. Matches
           --background / --surface in index.css. */
        vec3 base = mix(
          vec3(0.020, 0.026, 0.052),
          vec3(0.055, 0.062, 0.125),
          smoothstep(1.0, 0.0, uv.y)
        );

        vec3 indigo = vec3(0.44, 0.36, 0.95);
        vec3 cyan   = vec3(0.25, 0.83, 0.95);
        vec3 violet = vec3(0.62, 0.42, 0.98);

        float r1 = ribbon(p, t,        0.62, 0.10, 1.7, 0.20);
        float r2 = ribbon(p, t * 1.4,  0.44, 0.13, 1.1, 0.14);
        float r3 = ribbon(p, t * 0.7,  0.78, 0.07, 2.3, 0.10);

        vec3 color = base;
        color += indigo * r1 * 0.20;
        color += cyan   * r2 * 0.13;
        color += violet * r3 * 0.10;

        /* Cool pool low on the screen, behind the composer, so the input
           area feels anchored rather than floating in the void. */
        float pool = smoothstep(0.55, 0.0, distance(vec2(uv.x, uv.y * 1.6), vec2(0.5, 0.0)));
        color += indigo * pool * 0.10;

        /* Vignette: pull the corners down so content stays the focus. */
        float vignette = smoothstep(1.15, 0.30, distance(uv, vec2(0.5)));
        color *= mix(0.55, 1.0, vignette);

        gl_FragColor = vec4(color, 1.0);
      }
    `,
    depthWrite: false,
    depthTest: false,
  });
  const gradientPlane = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), gradientMaterial);
  scene.add(gradientPlane);

  // --- Ember field: sparse, slow-rising motes of warm light. ---
  const PARTICLE_COUNT = 140;
  const positions = new Float32Array(PARTICLE_COUNT * 3);
  const speeds = new Float32Array(PARTICLE_COUNT);
  const sway = new Float32Array(PARTICLE_COUNT);

  for (let i = 0; i < PARTICLE_COUNT; i++) {
    positions[i * 3] = (Math.random() - 0.5) * 2.4;
    positions[i * 3 + 1] = (Math.random() - 0.5) * 2.2;
    positions[i * 3 + 2] = 0;
    speeds[i] = 0.015 + Math.random() * 0.04;
    sway[i] = Math.random() * Math.PI * 2;
  }

  const particleGeometry = new THREE.BufferGeometry();
  particleGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));

  // Soft radial sprite drawn once to a small canvas texture rather than
  // loaded from a file — keeps this component asset-free.
  const spriteCanvas = document.createElement("canvas");
  spriteCanvas.width = 64;
  spriteCanvas.height = 64;
  const ctx = spriteCanvas.getContext("2d");
  if (ctx) {
    const gradient = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    gradient.addColorStop(0, "rgba(224,236,255,0.85)");
    gradient.addColorStop(0.35, "rgba(120,180,255,0.35)");
    gradient.addColorStop(1, "rgba(120,180,255,0)");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 64, 64);
  }
  const spriteTexture = new THREE.CanvasTexture(spriteCanvas);

  const particleMaterial = new THREE.PointsMaterial({
    size: 0.035,
    map: spriteTexture,
    transparent: true,
    opacity: 0.55,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    sizeAttenuation: true,
  });
  const particles = new THREE.Points(particleGeometry, particleMaterial);
  scene.add(particles);

  const clock = new THREE.Clock();
  let animationFrameId = 0;

  const renderFrame = (): void => {
    const elapsed = clock.getElapsedTime();
    uniforms.uTime.value = elapsed;

    if (!prefersReducedMotion) {
      const posAttr = particleGeometry.attributes.position as THREE.BufferAttribute;
      for (let i = 0; i < PARTICLE_COUNT; i++) {
        let y = posAttr.getY(i) + speeds[i]! * 0.01;
        if (y > 1.1) y = -1.1;
        const x = posAttr.getX(i) + Math.sin(elapsed * 0.3 + sway[i]!) * 0.0005;
        posAttr.setXY(i, x, y);
      }
      posAttr.needsUpdate = true;
    }

    renderer.render(scene, camera);
    if (!prefersReducedMotion) {
      animationFrameId = requestAnimationFrame(renderFrame);
    }
  };
  renderFrame();

  const handleResize = (): void => {
    renderer.setSize(window.innerWidth, window.innerHeight);
    uniforms.uResolution.value.set(window.innerWidth, window.innerHeight);
  };
  window.addEventListener("resize", handleResize);

  return () => {
    cancelAnimationFrame(animationFrameId);
    window.removeEventListener("resize", handleResize);
    particleGeometry.dispose();
    particleMaterial.dispose();
    spriteTexture.dispose();
    gradientMaterial.dispose();
    gradientPlane.geometry.dispose();
    renderer.dispose();
    container.removeChild(renderer.domElement);
  };
}
