import { Suspense, useMemo, useRef, useEffect, useCallback } from 'react';
import { Canvas, useFrame, type ThreeEvent } from '@react-three/fiber';
import { OrbitControls, type OrbitControlsProps } from '@react-three/drei';
import { RotateCcw } from 'lucide-react';
import * as THREE from 'three';
import type { Device, Port, PortKind } from '@/types';
import { vlanRGB } from '@/lib/vlan';
import type { ThemeMode } from '@/lib/palette';

interface Switch3DProps {
  device: Device;
  ports: Port[];
  selectedPort: string | null;
  onPick: (port: Port) => void;
  theme: ThemeMode;
}

interface PortLayout {
  rows: number;
  cols: number;
  type: 'rj45' | 'sfp' | 'qsfp';
  extra?: { kind: 'sfp'; count: number };
}

function portLayout(kind: PortKind): PortLayout {
  switch (kind) {
    case 'rj45-24-2sfp':
      return { rows: 2, cols: 12, type: 'rj45', extra: { kind: 'sfp', count: 2 } };
    case 'sfp-5':
      return { rows: 1, cols: 5, type: 'sfp' };
    case 'qsfp-32':
      return { rows: 2, cols: 16, type: 'qsfp' };
    case 'sfp-48':
      return { rows: 4, cols: 12, type: 'sfp' };
    case 'rj45-4':
      return { rows: 1, cols: 4, type: 'rj45' };
  }
}

const PORT_BODY: Record<PortLayout['type'], { w: number; h: number; color: number }> = {
  rj45: { w: 0.42, h: 0.46, color: 0x0a0d10 },
  sfp: { w: 0.4, h: 0.32, color: 0x0c1014 },
  qsfp: { w: 0.46, h: 0.38, color: 0x0c1014 },
};

const BRAND_COLOR: Record<Device['platform'], number> = {
  cisco: 0x1ba0c4,
  mock: 0x5a6472,
  arista: 0x1a4cb8,
  pica8: 0x9a4a1a,
  mikrotik: 0xc4421a,
  mikrotik_swos: 0xb33a18,
  freebsd: 0x6b4ea8,
};

/* -------------------------------------------------------------------------
 * Single port — a small group with body, slot, LED, ring, and a VLAN stripe.
 *
 * Used for low-density layouts (RJ45-24, SFP-5, QSFP-32, RJ45-4). For the
 * 280-port Pica8 we render via instanced meshes (see <InstancedPortGrid />).
 * ------------------------------------------------------------------------- */

interface PortMeshProps {
  port: Port;
  type: PortLayout['type'];
  position: [number, number, number];
  selected: boolean;
  onPick: (port: Port) => void;
}

function ledColorFor(port: Port): number {
  if (port.state === 'up') return 0x4dd47a;
  if (port.state === 'disabled') return 0xd97a26;
  return 0x1f242a;
}

function PortMesh({ port, type, position, selected, onPick }: PortMeshProps) {
  const body = PORT_BODY[type];
  const ledRef = useRef<THREE.MeshBasicMaterial>(null);
  const baseLed = useMemo(() => ledColorFor(port), [port]);
  const stripeColor = useMemo(() => {
    const [r, g, b] = vlanRGB(port.untagged_vlan);
    return new THREE.Color(r, g, b);
  }, [port.untagged_vlan]);

  // 1Hz pulse driven by traffic — only on `up` ports with non-trivial traffic
  useFrame(({ clock }) => {
    const mat = ledRef.current;
    if (!mat) return;
    if (port.state === 'up' && port.traffic > 0.15) {
      const phase = (Math.sin(clock.elapsedTime * (1 + port.traffic) + port.index * 0.7) + 1) * 0.5;
      const intensity = 0.55 + phase * 0.45 * port.traffic;
      mat.color.setHex(baseLed).multiplyScalar(intensity);
    } else {
      mat.color.setHex(baseLed);
    }
  });

  const handlePick = useCallback(
    (e: ThreeEvent<MouseEvent>) => {
      e.stopPropagation();
      onPick(port);
    },
    [onPick, port],
  );

  return (
    <group position={position} onClick={handlePick}>
      <mesh>
        <boxGeometry args={[body.w, body.h, 0.18]} />
        <meshLambertMaterial color={body.color} />
      </mesh>
      <mesh position={[0, 0, 0.07]}>
        <boxGeometry args={[body.w * 0.78, body.h * (type === 'rj45' ? 0.72 : 0.55), 0.06]} />
        <meshBasicMaterial color={0x05080b} />
      </mesh>
      {/* LED */}
      <mesh position={[-body.w * 0.2, -body.h / 2 + 0.07, 0.1]}>
        <boxGeometry args={[body.w * 0.42, 0.05, 0.04]} />
        <meshBasicMaterial ref={ledRef} color={baseLed} />
      </mesh>
      {/* VLAN identity stripe */}
      {port.state !== 'down' && (
        <mesh position={[0, -body.h / 2 + 0.018, 0.1]}>
          <boxGeometry args={[body.w * 0.86, 0.025, 0.04]} />
          <meshBasicMaterial color={stripeColor} />
        </mesh>
      )}
      {/* Selection ring — VLAN colored when selected */}
      {selected && (
        <mesh position={[0, 0, -0.05]}>
          <boxGeometry args={[body.w + 0.1, body.h + 0.1, 0.02]} />
          <meshBasicMaterial color={stripeColor} transparent opacity={0.95} />
        </mesh>
      )}
    </group>
  );
}

/* -------------------------------------------------------------------------
 * Instanced grid — used when port count gets large. Shares one geometry +
 * material across all ports. The selection ring is still a per-port mesh
 * because it changes color, but everything else is instanced.
 * ------------------------------------------------------------------------- */

interface InstancedPortGridProps {
  ports: Port[];
  positions: THREE.Vector3[];
  type: PortLayout['type'];
  selected: string | null;
  onPick: (port: Port) => void;
}

function InstancedPortGrid({ ports, positions, type, selected, onPick }: InstancedPortGridProps) {
  const body = PORT_BODY[type];
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const ledRef = useRef<THREE.InstancedMesh>(null);
  const stripeRef = useRef<THREE.InstancedMesh>(null);

  // Set per-instance colors and transforms once. Color updates would normally
  // happen here if we modeled traffic on the instanced LEDs, but for huge
  // port counts the whole-board pulse reads as ambient noise rather than
  // distinct ports, so we keep them static.
  useEffect(() => {
    if (!meshRef.current || !ledRef.current || !stripeRef.current) return;
    const dummy = new THREE.Object3D();
    const ledColor = new THREE.Color();
    const stripe = new THREE.Color();
    ports.forEach((port, i) => {
      const pos = positions[i];
      if (!pos) return; // never index past the positions array
      dummy.position.copy(pos);
      dummy.updateMatrix();
      meshRef.current!.setMatrixAt(i, dummy.matrix);

      // LED instance
      dummy.position.set(pos.x - body.w * 0.2, pos.y - body.h / 2 + 0.07, pos.z + 0.1);
      dummy.scale.set(body.w * 0.42, 0.05, 0.04);
      dummy.updateMatrix();
      ledRef.current!.setMatrixAt(i, dummy.matrix);
      dummy.scale.set(1, 1, 1);
      ledColor.setHex(ledColorFor(port));
      ledRef.current!.setColorAt(i, ledColor);

      // Stripe instance
      dummy.position.set(pos.x, pos.y - body.h / 2 + 0.018, pos.z + 0.1);
      dummy.scale.set(body.w * 0.86, 0.025, 0.04);
      dummy.updateMatrix();
      stripeRef.current!.setMatrixAt(i, dummy.matrix);
      dummy.scale.set(1, 1, 1);
      const [r, g, b] = vlanRGB(port.untagged_vlan);
      stripe.setRGB(r, g, b);
      stripeRef.current!.setColorAt(i, stripe);
    });
    meshRef.current.instanceMatrix.needsUpdate = true;
    ledRef.current.instanceMatrix.needsUpdate = true;
    stripeRef.current.instanceMatrix.needsUpdate = true;
    if (ledRef.current.instanceColor) ledRef.current.instanceColor.needsUpdate = true;
    if (stripeRef.current.instanceColor) stripeRef.current.instanceColor.needsUpdate = true;
  }, [ports, positions, body.w, body.h]);

  const handlePick = useCallback(
    (e: ThreeEvent<MouseEvent>) => {
      e.stopPropagation();
      const id = e.instanceId;
      if (id == null) return;
      const port = ports[id];
      if (port) onPick(port);
    },
    [onPick, ports],
  );

  const selectedIdx = ports.findIndex((p) => p.name === selected);
  const selectedPort = selectedIdx >= 0 ? ports[selectedIdx] : null;
  const selectedPos = selectedIdx >= 0 ? positions[selectedIdx] : null;
  const selectedColor = useMemo(() => {
    if (!selectedPort) return new THREE.Color(0xffffff);
    const [r, g, b] = vlanRGB(selectedPort.untagged_vlan);
    return new THREE.Color(r, g, b);
  }, [selectedPort]);

  return (
    <>
      <instancedMesh
        ref={meshRef}
        args={[undefined, undefined, ports.length]}
        onClick={handlePick}
      >
        <boxGeometry args={[body.w, body.h, 0.18]} />
        <meshLambertMaterial color={body.color} />
      </instancedMesh>
      <instancedMesh ref={ledRef} args={[undefined, undefined, ports.length]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshBasicMaterial />
      </instancedMesh>
      <instancedMesh ref={stripeRef} args={[undefined, undefined, ports.length]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshBasicMaterial />
      </instancedMesh>
      {selectedPos && (
        <mesh position={[selectedPos.x, selectedPos.y, selectedPos.z - 0.05]}>
          <boxGeometry args={[body.w + 0.1, body.h + 0.1, 0.02]} />
          <meshBasicMaterial color={selectedColor} transparent opacity={0.95} />
        </mesh>
      )}
    </>
  );
}

/* -------------------------------------------------------------------------
 * Chassis + scene contents
 * ------------------------------------------------------------------------- */

interface SceneProps extends Switch3DProps {
  layout: PortLayout;
  positions: THREE.Vector3[];
  isFreebsd: boolean;
}

function Scene({ device, ports, selectedPort, onPick, theme, layout, positions, isFreebsd }: SceneProps) {
  // The dark-mode canvas backdrop is near-black (#08090c, see <color> below).
  // The chassis must read as a *lighter* steel against it — earlier dark values
  // (0x1c2127 / 0x121518) sat almost on top of the background and the switch
  // vanished. Lambert + ambient 0.55 darkens these further at render, so they
  // are pitched well above the backdrop on purpose.
  const chassisColor = theme === 'dark' ? 0x343c46 : 0x2a3038;
  const frontColor = theme === 'dark' ? 0x252d35 : 0x1f242b;
  const topColor = theme === 'dark' ? 0x404a55 : 0x3a4250;
  const brand = BRAND_COLOR[device.platform];

  const chassisW = isFreebsd ? 6 : Math.max(6, layout.cols * 0.55 + 2);
  const chassisH = isFreebsd ? 1.2 : layout.rows * 0.65 + 1.0;
  const chassisD = 3.2;

  // Use instanced rendering above 60 ports (pica8 48-port + 100G 32-port both
  // fit; for smaller decks per-port meshes give nicer per-LED pulse).
  const useInstanced = ports.length > 60;

  return (
    <>
      {/* Instrument lighting: soft fill + a warm key + a cool accent rim so
          the chassis reads as a real material under control-room light. */}
      <ambientLight intensity={0.55} />
      <directionalLight position={[4, 6, 5]} intensity={0.78} />
      <directionalLight position={[-5, 2, -3]} intensity={0.4} color={0x7fa8ff} />
      <directionalLight position={[0, -3, 6]} intensity={0.18} color={0x9fd0ff} />

      {/* Chassis body */}
      <mesh>
        <boxGeometry args={[chassisW, chassisH, chassisD]} />
        <meshLambertMaterial color={chassisColor} />
      </mesh>
      {/* Top plate (fine bevel suggestion) */}
      <mesh position={[0, chassisH / 2 + 0.001, 0]}>
        <boxGeometry args={[chassisW * 0.99, 0.08, chassisD * 0.99]} />
        <meshLambertMaterial color={topColor} />
      </mesh>
      {/* Front inset */}
      <mesh position={[0, 0, chassisD / 2 + 0.025]}>
        <boxGeometry args={[chassisW - 0.4, chassisH - 0.3, 0.05]} />
        <meshLambertMaterial color={frontColor} />
      </mesh>
      {/* Brand chip */}
      <mesh position={[-chassisW / 2 + 0.55, 0, chassisD / 2 + 0.05]}>
        <boxGeometry args={[0.7, chassisH - 0.5, 0.04]} />
        <meshLambertMaterial color={brand} emissive={brand} emissiveIntensity={0.18} />
      </mesh>

      {/* Ports */}
      {useInstanced ? (
        <InstancedPortGrid
          ports={ports}
          positions={positions}
          type={layout.type}
          selected={selectedPort}
          onPick={onPick}
        />
      ) : (
        ports.map((port, i) => {
          const p = positions[i];
          if (!p) return null; // guard against a short positions array
          return (
            <PortMesh
              key={port.name}
              port={port}
              type={layout.type}
              position={[p.x, p.y, p.z]}
              selected={port.name === selectedPort}
              onPick={onPick}
            />
          );
        })
      )}
    </>
  );
}

/* -------------------------------------------------------------------------
 * Public component — owns the canvas and the orbit controls.
 * ------------------------------------------------------------------------- */

export function Switch3D({ device, ports, selectedPort, onPick, theme }: Switch3DProps) {
  const isFreebsd = device.platform === 'freebsd';
  const layout = portLayout(device.portKind);
  const orbitRef = useRef<OrbitControlsProps & { reset?: () => void } & { object?: unknown }>(null);

  const positions = useMemo<THREE.Vector3[]>(() => {
    const out: THREE.Vector3[] = [];
    const chassisD = 3.2;
    if (isFreebsd) {
      const startX = -1.65;
      for (let i = 0; i < ports.length; i++) {
        out.push(new THREE.Vector3(startX + i * 0.7, 0, chassisD / 2 + 0.15));
      }
      return out;
    }
    // Lay EVERY port out in a `layout.cols`-wide grid, flowing into as many
    // rows as needed. The faceplate's nominal row count is a hint for sizing,
    // but real devices can report more ports than rows*cols (e.g. PicOS
    // breakout sub-interfaces). Capping positions at the faceplate size left
    // positions[i] === undefined for the overflow and crashed the instanced
    // renderer — so we never cap: one position per port, always.
    const cols = Math.max(1, layout.cols);
    const rowCount = Math.max(layout.rows, Math.ceil(ports.length / cols));
    const colsW = cols * 0.55;
    const rowsH = rowCount * 0.65;
    const startX = -colsW / 2 + 0.275 + 0.7;
    const startY = rowsH / 2 - 0.325 - 0.05;
    for (let i = 0; i < ports.length; i++) {
      const r = Math.floor(i / cols);
      const c = i % cols;
      const x = startX + c * 0.55;
      const y = startY - r * 0.65;
      out.push(new THREE.Vector3(x, y, chassisD / 2 + 0.15));
    }
    return out;
  }, [layout, ports.length, isFreebsd]);

  return (
    <div className="relative h-full w-full overflow-hidden rounded-xl border border-border bg-bg-sunken shadow-[0_2px_24px_-8px_rgba(0,0,0,0.6)_inset]">
      <Canvas
        dpr={[1, 2]}
        camera={{ position: [0, 4, 9], fov: 35, near: 0.1, far: 200 }}
        gl={{ antialias: true, alpha: true }}
      >
        <color attach="background" args={[theme === 'dark' ? '#08090c' : '#eef0f3']} />
        <fog attach="fog" args={[theme === 'dark' ? '#08090c' : '#eef0f3', 14, 30]} />
        <Suspense fallback={null}>
          <Scene
            device={device}
            ports={ports}
            selectedPort={selectedPort}
            onPick={onPick}
            theme={theme}
            layout={layout}
            positions={positions}
            isFreebsd={isFreebsd}
          />
        </Suspense>
        <OrbitControls
          ref={orbitRef as never}
          enablePan={false}
          minDistance={4}
          maxDistance={20}
          minPolarAngle={0.2}
          maxPolarAngle={Math.PI - 0.2}
        />
      </Canvas>

      {/* Top overlay */}
      <div className="pointer-events-none absolute left-0 right-0 top-0 flex items-start justify-between p-3">
        <div className="rounded-md bg-black/40 px-2 py-1 text-[11px] text-fg backdrop-blur-sm">
          <span className="nb-mono uppercase">{device.platform}</span>
          <span className="mx-1.5 text-fg-subtle">·</span>
          <span>{device.model}</span>
          <span className="mx-1.5 text-fg-subtle">·</span>
          <span className="nb-mono">{device.mgmt_ip}</span>
        </div>
        <button
          type="button"
          onClick={() => {
            // OrbitControls exposes `reset` via .reset() on the actual instance
            const o = orbitRef.current as unknown as { reset?: () => void } | null;
            o?.reset?.();
          }}
          className="pointer-events-auto rounded-md border border-border-strong bg-bg-elev-1/80 p-1.5 text-fg-muted backdrop-blur-sm hover:text-fg"
          title="Reset view"
        >
          <RotateCcw size={14} />
        </button>
      </div>

      {/* Bottom legend */}
      <div className="pointer-events-none absolute bottom-2 left-2 right-2 flex flex-wrap items-center gap-3 rounded-md bg-black/40 px-2.5 py-1.5 text-[10px] uppercase tracking-wider text-fg-muted backdrop-blur-sm">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-success" /> link up
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-warn" /> admin disabled
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-fg-subtle/60" /> down
        </span>
        <span className="ml-auto text-fg-subtle">drag · scroll · click</span>
      </div>
    </div>
  );
}
