// Northbound — 3D switch + topology, three.js with custom orbit
// Stylized flat-shaded chassis, port grid with emissive LEDs.

const THREE = window.THREE;

function makeOrbitController(camera, dom, target = new THREE.Vector3(0, 0, 0)) {
  let radius = camera.position.distanceTo(target);
  let theta = Math.atan2(camera.position.x - target.x, camera.position.z - target.z);
  let phi = Math.acos(Math.min(1, Math.max(-1, (camera.position.y - target.y) / radius)));
  const min = { phi: 0.18, radius: 1.5 };
  const max = { phi: Math.PI - 0.18, radius: 30 };
  let dragging = false; let lx = 0, ly = 0;
  function update() {
    const sinPhi = Math.sin(phi);
    camera.position.x = target.x + radius * sinPhi * Math.sin(theta);
    camera.position.z = target.z + radius * sinPhi * Math.cos(theta);
    camera.position.y = target.y + radius * Math.cos(phi);
    camera.lookAt(target);
  }
  function onDown(e) { dragging = true; lx = e.clientX; ly = e.clientY; dom.setPointerCapture?.(e.pointerId); }
  function onUp(e) { dragging = false; dom.releasePointerCapture?.(e.pointerId); }
  function onMove(e) {
    if (!dragging) return;
    const dx = e.clientX - lx, dy = e.clientY - ly;
    lx = e.clientX; ly = e.clientY;
    theta -= dx * 0.008;
    phi = Math.min(max.phi, Math.max(min.phi, phi - dy * 0.008));
    update();
  }
  function onWheel(e) {
    e.preventDefault();
    radius = Math.min(max.radius, Math.max(min.radius, radius * (1 + e.deltaY * 0.0015)));
    update();
  }
  dom.addEventListener('pointerdown', onDown);
  dom.addEventListener('pointerup', onUp);
  dom.addEventListener('pointercancel', onUp);
  dom.addEventListener('pointermove', onMove);
  dom.addEventListener('wheel', onWheel, { passive: false });
  update();
  return {
    reset(t = 0) {
      radius = camera.userData.initRadius || radius;
      theta = camera.userData.initTheta ?? theta;
      phi = camera.userData.initPhi ?? phi;
      update();
    },
    dispose() {
      dom.removeEventListener('pointerdown', onDown);
      dom.removeEventListener('pointerup', onUp);
      dom.removeEventListener('pointercancel', onUp);
      dom.removeEventListener('pointermove', onMove);
      dom.removeEventListener('wheel', onWheel);
    },
    setInit() {
      camera.userData.initRadius = radius;
      camera.userData.initTheta = theta;
      camera.userData.initPhi = phi;
    },
  };
}

// ---------- 3D Switch ----------
function Switch3D({ device, ports, selectedPort, onPick, theme }) {
  const mountRef = React.useRef(null);
  const stateRef = React.useRef(null);
  const [hover, setHover] = React.useState(null);

  // Layout per port kind
  function portLayout(kind, count) {
    // returns {rows, cols, type: 'rj45' | 'sfp' | 'qsfp', faceW, faceH}
    if (kind === 'rj45-24-2sfp') return { rows: 2, cols: 12, type: 'rj45', extra: { kind: 'sfp', count: 2 } };
    if (kind === 'sfp-5') return { rows: 1, cols: 5, type: 'sfp' };
    if (kind === 'qsfp-32') return { rows: 2, cols: 16, type: 'qsfp' };
    if (kind === 'sfp-48') return { rows: 4, cols: 12, type: 'sfp' };
    if (kind === 'rj45-4') return { rows: 1, cols: 4, type: 'rj45' };
    return { rows: 1, cols: count, type: 'rj45' };
  }

  React.useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    const w = mount.clientWidth, h = mount.clientHeight;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(w, h);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mount.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, w / h, 0.1, 200);
    camera.position.set(0, 4, 9);
    const themeBg = theme === 'dark' ? 0x0c0f12 : 0xeef0f3;
    scene.fog = new THREE.Fog(themeBg, 14, 30);

    // Lights — stylized flat
    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 0.7); key.position.set(4, 6, 5); scene.add(key);
    const rim = new THREE.DirectionalLight(0x88aaff, 0.35); rim.position.set(-5, 2, -3); scene.add(rim);

    // Layout
    const layout = portLayout(device.portKind, device.portCount);
    const isFreebsd = device.platform === 'freebsd';
    // Chassis dimensions
    const chassisW = isFreebsd ? 6 : Math.max(6, layout.cols * 0.55 + 2);
    const chassisH = isFreebsd ? 1.2 : (layout.rows * 0.65 + 1.0);
    const chassisD = 3.2;

    const chassisMat = new THREE.MeshLambertMaterial({ color: theme === 'dark' ? 0x1c2127 : 0x2a3038 });
    const chassis = new THREE.Mesh(new THREE.BoxGeometry(chassisW, chassisH, chassisD), chassisMat);
    scene.add(chassis);

    // Top stripe / badge plate
    const topPlate = new THREE.Mesh(
      new THREE.BoxGeometry(chassisW * 0.99, 0.08, chassisD * 0.99),
      new THREE.MeshLambertMaterial({ color: theme === 'dark' ? 0x252b32 : 0x3a4250 })
    );
    topPlate.position.y = chassisH / 2 + 0.001;
    scene.add(topPlate);

    // Front face (slightly inset, matte lighter)
    const frontInsetMat = new THREE.MeshLambertMaterial({ color: theme === 'dark' ? 0x121518 : 0x1f242b });
    const frontInset = new THREE.Mesh(
      new THREE.BoxGeometry(chassisW - 0.4, chassisH - 0.3, 0.05),
      frontInsetMat
    );
    frontInset.position.set(0, 0, chassisD / 2 + 0.025);
    scene.add(frontInset);

    // Brand chip on left
    const brandColor = device.platform === 'mikrotik' ? 0x1f7a3a : device.platform === 'arista' ? 0x1a4cb8 : device.platform === 'pica8' ? 0x9a4a1a : 0x6b4ea8;
    const brand = new THREE.Mesh(
      new THREE.BoxGeometry(0.7, chassisH - 0.5, 0.04),
      new THREE.MeshLambertMaterial({ color: brandColor, emissive: brandColor, emissiveIntensity: 0.15 })
    );
    brand.position.set(-chassisW / 2 + 0.55, 0, chassisD / 2 + 0.05);
    scene.add(brand);

    // Build ports
    const portMeshes = []; // {mesh, led, port, name, idx}
    const portsArr = ports || [];

    function buildPort(idx, port, type, x, y) {
      const g = new THREE.Group();
      let bodyW, bodyH, bodyColor;
      if (type === 'rj45') { bodyW = 0.42; bodyH = 0.46; bodyColor = 0x0a0d10; }
      else if (type === 'sfp') { bodyW = 0.40; bodyH = 0.32; bodyColor = 0x0c1014; }
      else { bodyW = 0.46; bodyH = 0.38; bodyColor = 0x0c1014; } // qsfp
      const body = new THREE.Mesh(
        new THREE.BoxGeometry(bodyW, bodyH, 0.18),
        new THREE.MeshLambertMaterial({ color: bodyColor })
      );
      // small inset slot
      const slot = new THREE.Mesh(
        new THREE.BoxGeometry(bodyW * 0.78, bodyH * (type === 'rj45' ? 0.72 : 0.55), 0.06),
        new THREE.MeshBasicMaterial({ color: theme === 'dark' ? 0x05080b : 0x0a0e12 })
      );
      slot.position.z = 0.07;
      body.add(slot);

      // LED color: link-up = LINK GREEN (always), disabled = amber, down = dim
      // VLAN identity is shown in selection ring + 2D card, not the LED itself.
      let ledColor = 0x1a1f24;
      let isLive = false;
      if (port) {
        if (port.state === 'up') {
          ledColor = 0x4dd47a; // link green
          isLive = true;
        } else if (port.state === 'disabled') {
          ledColor = 0xd97a26;
        } else {
          ledColor = 0x1f242a;
        }
      }
      const led = new THREE.Mesh(
        new THREE.BoxGeometry(bodyW * 0.42, 0.05, 0.04),
        new THREE.MeshBasicMaterial({ color: ledColor })
      );
      led.position.set(-bodyW * 0.20, -bodyH / 2 + 0.07, 0.10);
      body.add(led);

      // Selection ring — takes VLAN color when selected
      const ring = new THREE.Mesh(
        new THREE.BoxGeometry(bodyW + 0.08, bodyH + 0.08, 0.02),
        new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0 })
      );
      ring.position.z = -0.05;
      body.add(ring);

      // Tiny VLAN identity stripe along the bottom of the port (subtle)
      let stripe = null;
      if (port && port.state !== 'down' && port.untagged_vlan != null) {
        const [vr, vg, vb] = window.vlanRGB(port.untagged_vlan);
        stripe = new THREE.Mesh(
          new THREE.BoxGeometry(bodyW * 0.86, 0.025, 0.04),
          new THREE.MeshBasicMaterial({ color: new THREE.Color(vr, vg, vb).getHex() })
        );
        stripe.position.set(0, -bodyH / 2 + 0.018, 0.10);
        body.add(stripe);
      }

      g.add(body);
      g.position.set(x, y, chassisD / 2 + 0.06 + 0.09);
      g.userData = { port, idx, body, led, ring, baseLedColor: ledColor };
      scene.add(g);
      portMeshes.push(g);
    }

    if (!isFreebsd) {
      const colsW = layout.cols * 0.55;
      const rowsH = layout.rows * 0.65;
      const startX = -colsW / 2 + 0.275 + 0.7; // shift right to accommodate brand
      const startY = rowsH / 2 - 0.325 - 0.05;
      let idx = 0;
      // Pairs of ports for rj45-24 use a "stacked" look (industrial), but we keep grid
      for (let r = 0; r < layout.rows; r++) {
        for (let c = 0; c < layout.cols; c++) {
          const port = portsArr[idx];
          if (!port) { idx++; continue; }
          const x = startX + c * 0.55;
          const y = startY - r * 0.65;
          buildPort(idx, port, layout.type, x, y);
          idx++;
        }
      }
      // SFP+ block on the right (mikrotik 24+2)
      if (layout.extra?.kind === 'sfp') {
        for (let i = 0; i < layout.extra.count; i++) {
          const port = portsArr[idx];
          if (!port) { idx++; continue; }
          const x = startX + layout.cols * 0.55 + 0.2 + i * 0.55;
          const y = 0;
          buildPort(idx, port, 'sfp', x, y);
          idx++;
        }
      }
    } else {
      // FreeBSD: 4 RJ45 + console-ish look
      const startX = -1.65;
      for (let i = 0; i < portsArr.length; i++) {
        buildPort(i, portsArr[i], 'rj45', startX + i * 0.7, 0);
      }
    }

    // Orbit
    const orbit = makeOrbitController(camera, renderer.domElement, new THREE.Vector3(0, 0, 0));
    orbit.setInit();

    // Picking
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    function onClick(e) {
      const r = renderer.domElement.getBoundingClientRect();
      mouse.x = ((e.clientX - r.left) / r.width) * 2 - 1;
      mouse.y = -((e.clientY - r.top) / r.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      const hits = raycaster.intersectObjects(portMeshes, true);
      if (hits.length) {
        let g = hits[0].object;
        while (g.parent && !g.userData?.port) g = g.parent;
        if (g.userData?.port) onPick?.(g.userData.port);
      }
    }
    function onMove(e) {
      const r = renderer.domElement.getBoundingClientRect();
      mouse.x = ((e.clientX - r.left) / r.width) * 2 - 1;
      mouse.y = -((e.clientY - r.top) / r.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      const hits = raycaster.intersectObjects(portMeshes, true);
      if (hits.length) {
        let g = hits[0].object;
        while (g.parent && !g.userData?.port) g = g.parent;
        setHover(g.userData?.port?.name || null);
      } else setHover(null);
    }
    renderer.domElement.addEventListener('click', onClick);
    renderer.domElement.addEventListener('pointermove', onMove);
    renderer.domElement.addEventListener('pointerleave', () => setHover(null));

    // Resize
    const onResize = () => {
      const w2 = mount.clientWidth, h2 = mount.clientHeight;
      renderer.setSize(w2, h2);
      camera.aspect = w2 / h2;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(onResize); ro.observe(mount);

    stateRef.current = { renderer, scene, camera, orbit, portMeshes, mount, ro };

    // Animation loop
    let running = true;
    const start = performance.now();
    function loop(now) {
      if (!running) return;
      const t = (now - start) / 1000;
      // pulse traffic on up ports
      for (const g of portMeshes) {
        const p = g.userData.port;
        if (!p) continue;
        const base = g.userData.baseLedColor;
        const ledMat = g.userData.led.material;
        if (p.state === 'up' && p.traffic > 0.15) {
          const phase = (Math.sin(t * (1.0 + p.traffic) + p.index * 0.7) + 1) * 0.5;
          const intensity = 0.55 + phase * 0.45 * p.traffic;
          ledMat.color.setHex(base);
          ledMat.color.multiplyScalar(intensity);
        }
      }
      renderer.render(scene, camera);
      requestAnimationFrame(loop);
    }
    requestAnimationFrame(loop);

    return () => {
      running = false;
      ro.disconnect();
      orbit.dispose();
      renderer.domElement.removeEventListener('click', onClick);
      renderer.domElement.removeEventListener('pointermove', onMove);
      renderer.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, [device.id, theme]);

  // Selection ring update — ring takes VLAN color of selected port
  React.useEffect(() => {
    const s = stateRef.current; if (!s) return;
    for (const g of s.portMeshes) {
      const ring = g.userData.ring;
      const isSel = g.userData.port?.name === selectedPort;
      ring.material.opacity = isSel ? 0.95 : 0;
      if (isSel && g.userData.port?.untagged_vlan != null) {
        const [r, gg, b] = window.vlanRGB(g.userData.port.untagged_vlan);
        ring.material.color.setRGB(r, gg, b);
      } else {
        ring.material.color.setHex(0xffffff);
      }
    }
  }, [selectedPort]);

  return (
    <div className="nb-3d-wrap">
      <div className="nb-3d-mount" ref={mountRef} />
      <div className="nb-3d-overlay">
        <div className="nb-3d-overlay__top">
          <div className="nb-3d-meta">
            <span className="nb-mono">{device.platform.toUpperCase()}</span>
            <span className="nb-3d-meta__sep">·</span>
            <span>{device.model}</span>
            <span className="nb-3d-meta__sep">·</span>
            <span className="nb-mono">{device.mgmt_ip}</span>
          </div>
          <button className="nb-iconbtn nb-iconbtn--floating" title="Reset view"
            onClick={() => stateRef.current?.orbit?.reset()}>
            <Icon name="reset" size={14} />
          </button>
        </div>
        {hover && <div className="nb-3d-hover">{hover}</div>}
        <div className="nb-3d-overlay__legend">
          <span><span className="nb-led nb-led--up" /> link up</span>
          <span><span className="nb-led nb-led--disabled" /> admin disabled</span>
          <span><span className="nb-led nb-led--down" /> down</span>
          <span className="nb-3d-hint">drag to orbit · scroll to zoom</span>
        </div>
      </div>
    </div>
  );
}

// ---------- 3D Topology ----------
function Topology3D({ env, devices, links, onPickDevice, theme, ambient = false }) {
  const mountRef = React.useRef(null);
  const stateRef = React.useRef(null);

  React.useEffect(() => {
    const mount = mountRef.current; if (!mount) return;
    const w = mount.clientWidth, h = mount.clientHeight;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(w, h);
    mount.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 200);
    camera.position.set(0, 8, 14);
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const key = new THREE.DirectionalLight(0xffffff, 0.6); key.position.set(5, 9, 6); scene.add(key);

    // Position devices by role
    const positions = {};
    const byRole = { spine: [], leaf: [], router: [], vpn: [] };
    for (const d of devices) byRole[d.role].push(d);
    function lay(arr, y, zSpread = 4) {
      const n = arr.length;
      arr.forEach((d, i) => {
        const x = n === 1 ? 0 : -((n - 1) * 1.6) / 2 + i * 1.6;
        positions[d.id] = new THREE.Vector3(x, y, 0 + (Math.random() - 0.5) * zSpread * 0.0);
      });
    }
    lay(byRole.spine, 1.5);
    lay(byRole.leaf, -0.5);
    lay(byRole.router, -2.5);
    lay(byRole.vpn, -2.5);
    // shift router/vpn so they don't overlap if both
    if (byRole.router.length && byRole.vpn.length) {
      byRole.router.forEach((d, i) => positions[d.id].x -= 1.0);
      byRole.vpn.forEach((d, i) => positions[d.id].x += 1.0);
    }

    // Boxes
    const boxMeshes = [];
    for (const d of devices) {
      const w0 = d.role === 'spine' ? 1.6 : d.role === 'leaf' ? 1.4 : 1.0;
      const h0 = 0.4;
      const d0 = 0.7;
      const color = d.platform === 'mikrotik' ? 0x1f7a3a : d.platform === 'arista' ? 0x1a4cb8 : d.platform === 'pica8' ? 0x9a4a1a : 0x6b4ea8;
      const body = new THREE.Mesh(
        new THREE.BoxGeometry(w0, h0, d0),
        new THREE.MeshLambertMaterial({ color: theme === 'dark' ? 0x1c2127 : 0x2a3038 })
      );
      const stripe = new THREE.Mesh(
        new THREE.BoxGeometry(w0 * 0.96, 0.06, d0 * 0.96),
        new THREE.MeshLambertMaterial({ color, emissive: color, emissiveIntensity: 0.4 })
      );
      stripe.position.y = h0 / 2 + 0.02;
      body.add(stripe);
      const p = positions[d.id];
      body.position.copy(p);
      body.userData = { device: d };
      scene.add(body);
      boxMeshes.push(body);
    }

    // Links — fiber (cyan dashed) vs copper (warm solid)
    const linkMeshes = [];
    for (const [a, b, kind] of links) {
      const pa = positions[a], pb = positions[b]; if (!pa || !pb) continue;
      const mid = new THREE.Vector3().addVectors(pa, pb).multiplyScalar(0.5);
      mid.y -= 0.3;
      const curve = new THREE.QuadraticBezierCurve3(pa, mid, pb);
      const points = curve.getPoints(40);
      const geom = new THREE.BufferGeometry().setFromPoints(points);
      const isFiber = kind === 'fiber' || kind == null;
      const mat = isFiber
        ? new THREE.LineDashedMaterial({ color: 0x6bd0e8, transparent: true, opacity: 0.7, dashSize: 0.18, gapSize: 0.10 })
        : new THREE.LineBasicMaterial({ color: 0xc78a52, transparent: true, opacity: 0.7 });
      const line = new THREE.Line(geom, mat);
      if (isFiber) line.computeLineDistances();
      scene.add(line);
      // Traffic shimmer dot
      const dotColor = isFiber ? 0x9be8f4 : 0xefc89a;
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.05, 12, 12), new THREE.MeshBasicMaterial({ color: dotColor }));
      scene.add(dot);
      linkMeshes.push({ curve, dot, phase: Math.random(), isFiber });
    }

    const orbit = makeOrbitController(camera, renderer.domElement, new THREE.Vector3(0, 0, 0));
    orbit.setInit();

    if (ambient) {
      // Ambient: slow auto-rotate, ignore user
      // We still allow setting a slow rotation
    }

    // Picking devices
    const ray = new THREE.Raycaster(); const m = new THREE.Vector2();
    function onClick(e) {
      const r = renderer.domElement.getBoundingClientRect();
      m.x = ((e.clientX - r.left) / r.width) * 2 - 1;
      m.y = -((e.clientY - r.top) / r.height) * 2 + 1;
      ray.setFromCamera(m, camera);
      const hits = ray.intersectObjects(boxMeshes, true);
      if (hits.length) {
        let n = hits[0].object;
        while (n.parent && !n.userData?.device) n = n.parent;
        if (n.userData?.device) onPickDevice?.(n.userData.device);
      }
    }
    if (!ambient) renderer.domElement.addEventListener('click', onClick);

    const onResize = () => {
      const w2 = mount.clientWidth, h2 = mount.clientHeight;
      renderer.setSize(w2, h2);
      camera.aspect = w2 / h2;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(onResize); ro.observe(mount);

    stateRef.current = { renderer, orbit };
    let running = true;
    const start = performance.now();
    let cameraAngle = 0;
    function loop(now) {
      if (!running) return;
      const t = (now - start) / 1000;
      for (const lm of linkMeshes) {
        const p = ((t * 0.25 + lm.phase) % 1);
        const pt = lm.curve.getPoint(p);
        lm.dot.position.copy(pt);
        lm.dot.material.opacity = 0.6 + 0.4 * Math.sin(t * 2 + lm.phase * 6.28);
      }
      if (ambient) {
        cameraAngle += 0.0015;
        const r = 14;
        camera.position.x = Math.sin(cameraAngle) * r;
        camera.position.z = Math.cos(cameraAngle) * r;
        camera.position.y = 7 + Math.sin(t * 0.5) * 0.4;
        camera.lookAt(0, 0, 0);
      }
      renderer.render(scene, camera);
      requestAnimationFrame(loop);
    }
    requestAnimationFrame(loop);

    return () => {
      running = false; ro.disconnect(); orbit.dispose();
      if (!ambient) renderer.domElement.removeEventListener('click', onClick);
      renderer.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, [env, theme, ambient]);

  return (
    <div className="nb-3d-wrap">
      <div className="nb-3d-mount" ref={mountRef} />
      {!ambient && (
        <div className="nb-3d-overlay">
          <div className="nb-3d-overlay__legend">
            <span><span className="nb-led nb-led--up" /> link active</span>
            <span><span style={{display:'inline-block',width:14,height:2,background:'#6bd0e8',borderRadius:1}} /> fiber</span>
            <span><span style={{display:'inline-block',width:14,height:2,background:'#c78a52',borderRadius:1}} /> copper</span>
            <span className="nb-3d-hint">drag to orbit · scroll to zoom · click a device</span>
          </div>
        </div>
      )}
    </div>
  );
}

window.Switch3D = Switch3D;
window.Topology3D = Topology3D;
