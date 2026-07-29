import { Suspense, useMemo, useRef, useEffect, useCallback } from 'react';
import { Canvas, useFrame, type ThreeEvent } from '@react-three/fiber';
import { OrbitControls, type OrbitControlsProps } from '@react-three/drei';
import { RotateCcw } from 'lucide-react';
import * as THREE from 'three';
import type { Device, Port } from '@/models';
import { deriveFaceplate, type ConnectorType } from '@/lib/faceplate';
import { vlanRGB } from '@/lib/vlan';
import type { ThemeMode } from '@/lib/palette';

interface Switch3DProps {
  device: Device;
  ports: Port[];
  selectedPort: string | null;
  onPick: (port: Port) => void;
  theme: ThemeMode;
}

/** Chassis sizing + port body geometry, derived from the faceplate below. */
interface PortLayout {
  rows: number;
  cols: number;
  type: 'rj45' | 'sfp' | 'qsfp';
}

// The old `portLayout(kind)` stereotype table lived here. It is gone: layout is
// now derived from the ports the device actually reports (lib/faceplate), and
// the per-platform stereotype survives only as that module's empty-list
// fallback. Keeping a second table here would let the two drift apart.

/** Cage footprint per connector type. Colour comes from the theme palette. */
const PORT_BODY: Record<PortLayout['type'], { w: number; h: number }> = {
  rj45: { w: 0.42, h: 0.46 },
  sfp: { w: 0.4, h: 0.32 },
  qsfp: { w: 0.46, h: 0.38 },
};

/**
 * Chassis + cage colours per theme.
 *
 * The previous values were near-black cages (0x0a0d10) on a near-black front
 * inset (0x1f242b) with no rim, so the whole faceplate read as one solid slab
 * and individual ports were invisible — in BOTH themes. The light theme was
 * also darker than the dark one, which is backwards.
 *
 * Each cage now gets a `bezel` rim that contrasts with both the chassis and the
 * cage interior, so a port reads as a distinct object regardless of theme.
 */
function facePalette(theme: ThemeMode) {
  return theme === 'dark'
    ? {
        // Deliberately mid-grey, not near-black: a dark chassis on a dark page
        // leaves the whole faceplate with nothing to catch the key light.
        chassis: 0x4d5766,
        front: 0x39424e,
        top: 0x5d6878,
        bezel: 0x9aa7b8, // bright machined rim — the main port separator
        cage: 0x0b1015, // dark cage mouth, so the rim reads against it
        slot: 0x05080b,
        pin: 0xd0aa3c, // gold contacts
        shield: 0x8b98a8, // EMI shield / cage lip on fibre ports
      }
    : {
        chassis: 0xbcc3cd, // light chassis, so dark cages stand out
        front: 0x99a2ae,
        top: 0xd2d8e0,
        bezel: 0x39424e, // dark rim against light chassis
        cage: 0x171c22,
        slot: 0x0d1116,
        pin: 0xb8912a,
        shield: 0x6d7886,
      };
}

/**
 * Depth ladder for the stacked plates that make up a port face.
 *
 * Every layer gets its OWN front-face depth, separated by a clear margin. Two
 * surfaces at the same z fight for the depth buffer and flicker as the camera
 * orbits — which is exactly what happened when the QSFP rib and the cage mouth
 * both ended at 0.105, and the shield lip ended level with the cage body.
 * Keep these distinct; do not collapse them to "close enough" values.
 */
const Z = {
  bezel: -0.05, // depth 0.10 -> front face at  0.00
  cage: 0.06, //   depth 0.10 -> front face at  0.11
  mouth: 0.13, //  depth 0.03 -> front face at  0.145
  detail: 0.17, // depth 0.02 -> front face at  0.18
} as const;

/**
 * The recognisable face of each connector type.
 *
 * A plain dark rectangle reads as "a hole", not as a port. Real panels are
 * identifiable at a glance because RJ45 has a latch keyway and gold contacts
 * while SFP/QSFP are letterbox cage mouths with a metal lip — so we model
 * exactly those cues. Only the per-port path draws this detail; the instanced
 * path (>60 ports) stays simple, where the extra geometry would cost far more
 * than it communicates.
 *
 * Materials are FLAT (lambert/basic, no metalness or roughness). Specular
 * highlights from a metallic material slide across 32 cages as the camera
 * moves and read as shimmer; a diffuse panel is calmer and easier to scan.
 */
function ConnectorFace({
  type,
  body,
  palette,
}: {
  type: PortLayout['type'];
  body: { w: number; h: number };
  palette: ReturnType<typeof facePalette>;
}) {
  if (type === 'rj45') {
    const ow = body.w * 0.72;
    const oh = body.h * 0.5;
    const cy = body.h * 0.07; // opening sits high; keyway hangs below it
    return (
      <>
        {/* Main opening */}
        <mesh position={[0, cy, Z.mouth]}>
          <boxGeometry args={[ow, oh, 0.03]} />
          <meshBasicMaterial color={palette.slot} />
        </mesh>
        {/* Latch keyway — the notch that makes an RJ45 unmistakable. Sits at
            the mouth depth and is only adjacent in Y, so no shared surface. */}
        <mesh position={[0, cy - oh / 2 - 0.035, Z.mouth]}>
          <boxGeometry args={[ow * 0.36, 0.09, 0.03]} />
          <meshBasicMaterial color={palette.slot} />
        </mesh>
        {/* 8 contacts along the top of the opening */}
        {Array.from({ length: 8 }, (_, i) => (
          <mesh key={i} position={[-ow / 2 + (ow * (i + 0.5)) / 8, cy + oh * 0.2, Z.detail]}>
            <boxGeometry args={[ow / 18, oh * 0.42, 0.02]} />
            <meshBasicMaterial color={palette.pin} />
          </mesh>
        ))}
      </>
    );
  }

  // SFP / SFP+ / QSFP — a letterbox cage mouth behind a shield lip.
  const ow = body.w * 0.82;
  const oh = body.h * (type === 'qsfp' ? 0.52 : 0.46);
  return (
    <>
      {/* Shield lip — one step behind the mouth, never level with it. */}
      <mesh position={[0, 0, Z.cage + 0.03]}>
        <boxGeometry args={[ow + 0.05, oh + 0.05, 0.03]} />
        <meshLambertMaterial color={palette.shield} />
      </mesh>
      {/* Cage mouth */}
      <mesh position={[0, 0, Z.mouth]}>
        <boxGeometry args={[ow, oh, 0.03]} />
        <meshBasicMaterial color={palette.slot} />
      </mesh>
      {/* QSFP mouths carry a visible divider rib, at detail depth so its front
          face never coincides with the mouth's. */}
      {type === 'qsfp' && (
        <mesh position={[0, 0, Z.detail]}>
          <boxGeometry args={[ow * 0.9, 0.018, 0.02]} />
          <meshBasicMaterial color={palette.shield} />
        </mesh>
      )}
    </>
  );
}

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
  palette: ReturnType<typeof facePalette>;
}

function ledColorFor(port: Port): number {
  if (port.state === 'up') return 0x4dd47a;
  if (port.state === 'disabled') return 0xd97a26;
  return 0x1f242a;
}

function PortMesh({ port, type, position, selected, onPick, palette }: PortMeshProps) {
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
      {/* Bezel — a rim slightly larger than the cage, sitting just behind it.
          This is what makes an individual port visible: without it the cage is
          a dark rectangle on a dark faceplate and the whole panel reads as one
          slab. Contrasts against the chassis in both themes. */}
      <mesh position={[0, 0, Z.bezel]}>
        <boxGeometry args={[body.w + 0.08, body.h + 0.08, 0.1]} />
        <meshLambertMaterial color={palette.bezel} />
      </mesh>
      {/* Cage plate — flat diffuse, not a metallic shroud. Metalness made the
          highlight slide across every cage as the camera moved. */}
      <mesh position={[0, 0, Z.cage]}>
        <boxGeometry args={[body.w, body.h, 0.1]} />
        <meshLambertMaterial color={palette.cage} />
      </mesh>
      <ConnectorFace type={type} body={body} palette={palette} />
      {/* LED and VLAN stripe ride in FRONT of every plate, at their own depth —
          previously both sat at 0.1, inside the cage plate's own span. */}
      <mesh position={[-body.w * 0.2, -body.h / 2 + 0.07, Z.detail + 0.02]}>
        <boxGeometry args={[body.w * 0.42, 0.05, 0.02]} />
        <meshBasicMaterial ref={ledRef} color={baseLed} />
      </mesh>
      {port.state !== 'down' && (
        <mesh position={[0, -body.h / 2 + 0.018, Z.detail + 0.02]}>
          <boxGeometry args={[body.w * 0.86, 0.025, 0.02]} />
          <meshBasicMaterial color={stripeColor} />
        </mesh>
      )}
      {/* Selection halo — must sit BEHIND the bezel and be wider than it, or it
          is buried inside the bezel volume and fights it for depth. */}
      {selected && (
        <mesh position={[0, 0, Z.bezel - 0.08]}>
          <boxGeometry args={[body.w + 0.18, body.h + 0.18, 0.02]} />
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
  palette: ReturnType<typeof facePalette>;
}

function InstancedPortGrid({
  ports,
  positions,
  type,
  selected,
  onPick,
  palette,
}: InstancedPortGridProps) {
  const body = PORT_BODY[type];
  const bezelRef = useRef<THREE.InstancedMesh>(null);
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const ledRef = useRef<THREE.InstancedMesh>(null);
  const stripeRef = useRef<THREE.InstancedMesh>(null);

  // Set per-instance colors and transforms once. Color updates would normally
  // happen here if we modeled traffic on the instanced LEDs, but for huge
  // port counts the whole-board pulse reads as ambient noise rather than
  // distinct ports, so we keep them static.
  useEffect(() => {
    if (!meshRef.current || !ledRef.current || !stripeRef.current || !bezelRef.current) return;
    const dummy = new THREE.Object3D();
    const ledColor = new THREE.Color();
    const stripe = new THREE.Color();
    ports.forEach((port, i) => {
      const pos = positions[i];
      if (!pos) return; // never index past the positions array
      dummy.position.set(pos.x, pos.y, pos.z + Z.cage);
      dummy.updateMatrix();
      meshRef.current!.setMatrixAt(i, dummy.matrix);

      // Bezel on its own rung of the depth ladder — overlapping the cage here
      // is what made the plates fight for depth and flicker.
      dummy.position.set(pos.x, pos.y, pos.z + Z.bezel);
      dummy.updateMatrix();
      bezelRef.current!.setMatrixAt(i, dummy.matrix);

      // LED instance
      dummy.position.set(pos.x - body.w * 0.2, pos.y - body.h / 2 + 0.07, pos.z + Z.detail + 0.02);
      dummy.scale.set(body.w * 0.42, 0.05, 0.04);
      dummy.updateMatrix();
      ledRef.current!.setMatrixAt(i, dummy.matrix);
      dummy.scale.set(1, 1, 1);
      ledColor.setHex(ledColorFor(port));
      ledRef.current!.setColorAt(i, ledColor);

      // Stripe instance
      dummy.position.set(pos.x, pos.y - body.h / 2 + 0.018, pos.z + Z.detail + 0.02);
      dummy.scale.set(body.w * 0.86, 0.025, 0.04);
      dummy.updateMatrix();
      stripeRef.current!.setMatrixAt(i, dummy.matrix);
      dummy.scale.set(1, 1, 1);
      const [r, g, b] = vlanRGB(port.untagged_vlan);
      stripe.setRGB(r, g, b);
      stripeRef.current!.setColorAt(i, stripe);
    });
    meshRef.current.instanceMatrix.needsUpdate = true;
    bezelRef.current.instanceMatrix.needsUpdate = true;
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
      {/* Bezel rim behind every cage — same purpose as in PortMesh: without it
          the cages are dark rectangles on a dark faceplate and no individual
          port is discernible. */}
      <instancedMesh ref={bezelRef} args={[undefined, undefined, ports.length]}>
        <boxGeometry args={[body.w + 0.08, body.h + 0.08, 0.1]} />
        <meshLambertMaterial color={palette.bezel} />
      </instancedMesh>
      <instancedMesh
        ref={meshRef}
        args={[undefined, undefined, ports.length]}
        onClick={handlePick}
      >
        <boxGeometry args={[body.w, body.h, 0.1]} />
        <meshLambertMaterial color={palette.cage} />
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
        <mesh position={[selectedPos.x, selectedPos.y, selectedPos.z + Z.bezel - 0.08]}>
          <boxGeometry args={[body.w + 0.18, body.h + 0.18, 0.02]} />
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
  const palette = facePalette(theme);
  const chassisColor = palette.chassis;
  const frontColor = palette.front;
  const topColor = palette.top;
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
      {/* Flat, even lighting: one ambient plus one white key from the front.
          The previous rig had two extra coloured rim lights and metallic
          materials, which slid a specular highlight across all 32 cages as the
          camera orbited and read as shimmer. Diffuse-only keeps the panel
          steady and legible while the camera moves. */}
      <ambientLight intensity={theme === 'dark' ? 0.9 : 0.85} />
      <directionalLight position={[1, 3, 8]} intensity={theme === 'dark' ? 0.55 : 0.45} />

      {/* Chassis body — flat diffuse. It was a metallic standard material lit
          by a three-light rig; the moving specular was a large part of the
          shimmer, and a painted-card look is steadier to read anyway. */}
      <mesh castShadow>
        <boxGeometry args={[chassisW, chassisH, chassisD]} />
        <meshLambertMaterial color={chassisColor} />
      </mesh>
      {/* Top plate (fine bevel suggestion) — slightly smoother so the lid edge
          highlight separates it from the body and gives a dimensional read. */}
      <mesh position={[0, chassisH / 2 + 0.001, 0]}>
        <boxGeometry args={[chassisW * 0.99, 0.08, chassisD * 0.99]} />
        <meshLambertMaterial color={topColor} />
      </mesh>
      {/* Front inset — recessed faceplate; a touch rougher/less metallic so it
          reads as a solid sunken panel the ports sit in, not a void. */}
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
          palette={palette}
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
              palette={palette}
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

/** Faceplate connector type -> the three port body geometries this scene has. */
function bodyTypeFor(connector: ConnectorType): PortLayout['type'] {
  switch (connector) {
    case 'qsfp':
      return 'qsfp';
    case 'sfp':
    case 'sfp28':
      return 'sfp';
    default:
      return 'rj45';
  }
}

export function Switch3D({ device, ports, selectedPort, onPick, theme }: Switch3DProps) {
  const isFreebsd = device.platform === 'freebsd';
  const orbitRef = useRef<OrbitControlsProps & { reset?: () => void } & { object?: unknown }>(null);

  // Layout comes from the ports the device actually reported, not from a guess
  // keyed off the platform string. `device.portKind` survives only as the
  // fallback for a device whose ports have not loaded yet.
  const faceplate = useMemo(() => deriveFaceplate(ports, device.portKind), [ports, device.portKind]);

  // Groups sit side by side, so a switch's SFP uplinks render to the right of
  // its access ports — one grid, group-aware, plus a one-column gap between.
  const layout = useMemo<PortLayout>(() => {
    if (faceplate.groups.length === 0) return { rows: 1, cols: 1, type: 'rj45' };
    const cols =
      faceplate.groups.reduce((n, g) => n + g.cols, 0) + (faceplate.groups.length - 1);
    const rows = faceplate.groups.reduce((n, g) => Math.max(n, g.rows), 1);
    // Body geometry follows the biggest group — the panel's dominant media.
    const dominant = faceplate.groups.reduce((a, b) => (b.slots.length > a.slots.length ? b : a));
    return { rows, cols, type: bodyTypeFor(dominant.connector) };
  }, [faceplate]);

  const positions = useMemo<THREE.Vector3[]>(() => {
    const chassisD = 3.2;
    if (isFreebsd) {
      const startX = -1.65;
      return ports.map((_, i) => new THREE.Vector3(startX + i * 0.7, 0, chassisD / 2 + 0.15));
    }

    const colsW = layout.cols * 0.55;
    const rowsH = layout.rows * 0.65;
    const startX = -colsW / 2 + 0.275 + 0.7;
    const startY = rowsH / 2 - 0.325 - 0.05;

    // Place by CAGE, then hand each port the position of the cage it lives in.
    // Breakout lanes share one cage (see lib/faceplate), so they land together
    // and are nudged apart only enough to stay individually pickable.
    const byPort = new Map<string, THREE.Vector3>();
    let colOffset = 0;
    for (const group of faceplate.groups) {
      for (const slot of group.slots) {
        const x = startX + (colOffset + slot.col) * 0.55;
        const y = startY - slot.row * 0.65;
        slot.ports.forEach((p, lane) => {
          const spread = slot.ports.length > 1 ? (lane - (slot.ports.length - 1) / 2) * 0.12 : 0;
          byPort.set(p.name, new THREE.Vector3(x, y + spread, chassisD / 2 + 0.15));
        });
      }
      colOffset += group.cols + 1;
    }

    // One position per port, always — a missing entry would leave
    // positions[i] undefined and crash the instanced renderer.
    return ports.map(
      (p, i) =>
        byPort.get(p.name) ??
        new THREE.Vector3(startX + (i % Math.max(1, layout.cols)) * 0.55, startY, chassisD / 2 + 0.15),
    );
  }, [faceplate, layout, ports, isFreebsd]);

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
          className="pointer-events-auto rounded-md border border-border-strong bg-bg-elev-1/80 p-1.5 text-fg-muted backdrop-blur-sm hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          aria-label="Reset camera view"
          title="Reset view"
        >
          <RotateCcw size={14} aria-hidden />
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
