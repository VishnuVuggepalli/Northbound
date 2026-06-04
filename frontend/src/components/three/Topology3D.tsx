import { Suspense, useMemo, useRef, useCallback } from 'react';
import { Canvas, useFrame, type ThreeEvent } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import type { Device, TopologyLink } from '@/types';
import type { ThemeMode } from '@/lib/palette';

interface Topology3DProps {
  devices: Device[];
  links: readonly TopologyLink[];
  theme: ThemeMode;
  ambient?: boolean;
  onPickDevice?: (device: Device) => void;
}

const PLATFORM_COLOR: Record<Device['platform'], number> = {
  cisco: 0x1ba0c4,
  mock: 0x5a6472,
  arista: 0x1a4cb8,
  pica8: 0x9a4a1a,
  mikrotik: 0xc4421a,
  mikrotik_swos: 0xb33a18,
  freebsd: 0x6b4ea8,
};

interface DeviceBoxProps {
  device: Device;
  position: THREE.Vector3;
  theme: ThemeMode;
  onClick: (d: Device) => void;
}

function DeviceBox({ device, position, theme, onClick }: DeviceBoxProps) {
  const w = device.role === 'spine' ? 1.6 : device.role === 'leaf' ? 1.4 : 1.0;
  const h = 0.4;
  const d = 0.7;
  const color = PLATFORM_COLOR[device.platform];
  const onPick = useCallback(
    (e: ThreeEvent<MouseEvent>) => {
      e.stopPropagation();
      onClick(device);
    },
    [device, onClick],
  );
  return (
    <group position={position}>
      <mesh onClick={onPick}>
        <boxGeometry args={[w, h, d]} />
        {/* Node body must read as lighter steel against the near-black dark
            backdrop (#0c0f12) — same fix as Switch3D's chassis; the prior
            0x1c2127 sat almost on the background. */}
        <meshLambertMaterial color={theme === 'dark' ? 0x343c46 : 0x2a3038} />
      </mesh>
      <mesh position={[0, h / 2 + 0.02, 0]}>
        <boxGeometry args={[w * 0.96, 0.06, d * 0.96]} />
        <meshLambertMaterial color={color} emissive={color} emissiveIntensity={0.4} />
      </mesh>
    </group>
  );
}

interface LinkLineProps {
  start: THREE.Vector3;
  end: THREE.Vector3;
  kind: 'fiber' | 'copper';
}

function LinkLine({ start, end, kind }: LinkLineProps) {
  const dotRef = useRef<THREE.Mesh>(null);
  const phase = useMemo(() => Math.random(), []);
  const curve = useMemo(() => {
    const mid = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5);
    mid.y -= 0.3;
    return new THREE.QuadraticBezierCurve3(start, mid, end);
  }, [start, end]);

  const points = useMemo(() => curve.getPoints(40), [curve]);
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry().setFromPoints(points);
    return g;
  }, [points]);

  const isFiber = kind === 'fiber';

  useFrame(({ clock }) => {
    if (!dotRef.current) return;
    const t = (clock.elapsedTime * 0.25 + phase) % 1;
    const pt = curve.getPoint(t);
    dotRef.current.position.copy(pt);
    const mat = dotRef.current.material as THREE.MeshBasicMaterial;
    mat.opacity = 0.6 + 0.4 * Math.sin(clock.elapsedTime * 2 + phase * 6.28);
  });

  return (
    <>
      {isFiber ? (
        <line>
          <primitive attach="geometry" object={geometry} />
          <lineDashedMaterial
            attach="material"
            color={0x6bd0e8}
            transparent
            opacity={0.7}
            dashSize={0.18}
            gapSize={0.1}
          />
        </line>
      ) : (
        <line>
          <primitive attach="geometry" object={geometry} />
          <lineBasicMaterial attach="material" color={0xc78a52} transparent opacity={0.7} />
        </line>
      )}
      <mesh ref={dotRef}>
        <sphereGeometry args={[0.05, 12, 12]} />
        <meshBasicMaterial color={isFiber ? 0x9be8f4 : 0xefc89a} transparent />
      </mesh>
    </>
  );
}

interface AmbientCameraProps {
  speed?: number;
}

/** Slowly orbits the camera around origin for the env-picker tiles. */
function AmbientCamera({ speed = 0.0015 }: AmbientCameraProps) {
  useFrame(({ camera, clock }) => {
    const angle = clock.elapsedTime * speed * 60;
    const r = 14;
    camera.position.x = Math.sin(angle) * r;
    camera.position.z = Math.cos(angle) * r;
    camera.position.y = 7 + Math.sin(clock.elapsedTime * 0.5) * 0.4;
    camera.lookAt(0, 0, 0);
  });
  return null;
}

function Scene({ devices, links, theme, ambient, onPickDevice }: Topology3DProps) {
  // Position devices by role, similar to the prototype's lay() helper.
  const positions = useMemo(() => {
    const map = new Map<string, THREE.Vector3>();
    const groups: Record<Device['role'], Device[]> = {
      spine: [],
      leaf: [],
      router: [],
      vpn: [],
    };
    for (const d of devices) groups[d.role].push(d);

    function lay(arr: Device[], y: number) {
      const n = arr.length;
      arr.forEach((d, i) => {
        const x = n === 1 ? 0 : -((n - 1) * 1.6) / 2 + i * 1.6;
        map.set(d.id, new THREE.Vector3(x, y, 0));
      });
    }
    lay(groups.spine, 1.5);
    lay(groups.leaf, -0.5);
    lay(groups.router, -2.5);
    lay(groups.vpn, -2.5);
    if (groups.router.length && groups.vpn.length) {
      groups.router.forEach((d) => {
        const v = map.get(d.id);
        if (v) v.x -= 1.0;
      });
      groups.vpn.forEach((d) => {
        const v = map.get(d.id);
        if (v) v.x += 1.0;
      });
    }
    return map;
  }, [devices]);

  return (
    <>
      <ambientLight intensity={0.6} />
      <directionalLight position={[5, 9, 6]} intensity={0.6} />
      {devices.map((d) => {
        const pos = positions.get(d.id);
        if (!pos) return null;
        return (
          <DeviceBox
            key={d.id}
            device={d}
            position={pos}
            theme={theme}
            onClick={(dev) => !ambient && onPickDevice?.(dev)}
          />
        );
      })}
      {links.map(([a, b, kind], i) => {
        const pa = positions.get(a);
        const pb = positions.get(b);
        if (!pa || !pb) return null;
        return <LinkLine key={`${a}-${b}-${i}`} start={pa} end={pb} kind={kind} />;
      })}
    </>
  );
}

export function Topology3D({ devices, links, theme, ambient = false, onPickDevice }: Topology3DProps) {
  return (
    <div className="relative h-full w-full overflow-hidden rounded-lg bg-[oklch(0.10_0.01_240)]">
      <Canvas
        dpr={[1, 2]}
        camera={{ position: [0, 8, 14], fov: 45, near: 0.1, far: 200 }}
        gl={{ antialias: true, alpha: true }}
      >
        <color attach="background" args={[theme === 'dark' ? '#0c0f12' : '#eef0f3']} />
        <Suspense fallback={null}>
          <Scene devices={devices} links={links} theme={theme} ambient={ambient} onPickDevice={onPickDevice} />
        </Suspense>
        {ambient ? (
          <AmbientCamera />
        ) : (
          <OrbitControls
            enablePan
            minDistance={6}
            maxDistance={26}
            minPolarAngle={0.2}
            maxPolarAngle={Math.PI - 0.2}
          />
        )}
      </Canvas>

      {!ambient && (
        <div className="pointer-events-none absolute bottom-2 left-2 right-2 flex flex-wrap items-center gap-3 rounded-md bg-black/40 px-2.5 py-1.5 text-[10px] uppercase tracking-wider text-fg-muted backdrop-blur-sm">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full bg-success" /> link active
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-[2px] w-3.5 rounded-full" style={{ background: '#6bd0e8' }} /> fiber
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-[2px] w-3.5 rounded-full" style={{ background: '#c78a52' }} /> copper
          </span>
          <span className="ml-auto text-fg-subtle">drag · scroll · click a device</span>
        </div>
      )}
    </div>
  );
}
