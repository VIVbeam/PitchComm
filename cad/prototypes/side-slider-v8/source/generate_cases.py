#!/usr/bin/env python3
"""
PitchComm field-case generator (maintainer tool).

Builds the three field pods from dev/cad/profiles.json with trimesh +
manifold3d CSG.  The shell is a thin flat tapered tray (wide rim, inset-lip
lid, screw entries through the floor into blind pilot bosses on the lid inner
face, internal deck between cell and board, friction charge cap, two-loop
strap carriers).  The controls live on a raised control
deck on the lid: a sloped display head plus, where used, a flat button
plateau.  Only the control deck is tilted.

Product output (cad/unbranded/):
    exports/<style>_body.stl, _lid.stl, _deck.stl, _charge_cap.stl,
    exports/<style>_<mount>_carrier.stl, _plunger_*.stl, _label_*.stl,
    exports/<style>_display_bezel.stl
    exports/*_color.stl copies, exports/<style>_colored.3mf,
    exports/<style>_lid_colored.3mf, exports/palette.json,
    exports/fit_coupon.stl
    preview.png, parts-preview.png, mounts-preview.png

Maintainer output (dev/cad/):
    dimensions.json

Usage:
    python dev/cad/generate_cases.py [--only receiver|wrist|keypad]
                                     [--no-preview]
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
import time
from types import SimpleNamespace
import zipfile
from xml.sax.saxutils import escape

import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))            # dev/cad
ROOT = os.path.dirname(os.path.dirname(HERE))                # repo root
EXPORTS_DIR = os.path.join(ROOT, "cad", "unbranded", "exports")
PREVIEW_DIR = os.path.join(ROOT, "cad", "unbranded")
PROFILES_PATH = os.path.join(HERE, "profiles.json")
DIMS_PATH = os.path.join(HERE, "dimensions.json")
ENGINE = "manifold"
SECTIONS = 48
ARC_SEG = 16
BIG = 600.0


# ==========================================================================
# geometry helpers
# ==========================================================================

def rr_poly(w, l, r, seg=ARC_SEG):
    r = float(min(r, w / 2.0 - 1e-6, l / 2.0 - 1e-6))
    pts = []
    for cx, cy, a0 in ((w - r, l - r, 0.0), (r, l - r, 90.0),
                       (r, r, 180.0), (w - r, r, 270.0)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90.0 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return np.asarray(pts, dtype=float)


def extrude_poly(poly, z0, z1):
    n = len(poly)
    v = np.vstack([np.column_stack([poly, np.full(n, z0)]),
                   np.column_stack([poly, np.full(n, z1)])])
    faces = []
    for i in range(1, n - 1):
        faces.append((0, i + 1, i))
        faces.append((n, n + i, n + i + 1))
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j))
        faces.append((i, n + j, n + i))
    m = trimesh.Trimesh(vertices=v, faces=np.asarray(faces), process=True)
    if not m.is_winding_consistent:
        trimesh.repair.fix_normals(m)
    return m


def prism_axis(poly, axis, a0, a1, offset=(0.0, 0.0, 0.0)):
    m = extrude_poly(poly, a0, a1)
    if axis == 'x':
        T = np.array([[0, 0, 1, 0], [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1]], float)
    elif axis == 'y':
        T = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], float)
    elif axis == 'z':
        T = np.eye(4)
    else:
        raise ValueError(axis)
    m.apply_transform(T)
    m.apply_translation(offset)
    return m


def bop(op, meshes):
    out = getattr(trimesh.boolean, op)(list(meshes), engine=ENGINE)
    if isinstance(out, (list, tuple)):
        out = out[0]
    return out


def uni(*meshes):
    return bop('union', [m for m in meshes if m is not None])


def dif(base, tools):
    if not isinstance(tools, (list, tuple)):
        tools = [tools]
    return bop('difference', [base] + [t for t in tools if t is not None])


def inter(*meshes):
    return bop('intersection', [m for m in meshes if m is not None])


def cyl(d, h, axis='z', pos=(0.0, 0.0, 0.0), sections=SECTIONS):
    m = trimesh.creation.cylinder(radius=d / 2.0, height=h, sections=sections)
    if axis == 'x':
        m.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2.0, [0, 1, 0]))
    elif axis == 'y':
        m.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2.0, [1, 0, 0]))
    m.apply_translation(pos)
    return m


def cyl_at(d, z0, z1, x, y):
    return cyl(d, z1 - z0, 'z', (x, y, (z0 + z1) / 2.0))


def rbox(w, l, h, rv, rh, pos=(0.0, 0.0, 0.0)):
    x0, y0, z0 = pos
    pz = prism_axis(rr_poly(w, l, rv), 'z', 0.0, h)
    px = prism_axis(rr_poly(l, h, rh), 'x', 0.0, w)
    py = prism_axis(rr_poly(w, h, rh), 'y', 0.0, l)
    m = inter(pz, px, py)
    m.apply_translation((x0, y0, z0))
    return m


def box(w, l, h, pos=(0.0, 0.0, 0.0)):
    m = trimesh.creation.box(extents=(w, l, h))
    m.apply_translation((pos[0] + w / 2.0, pos[1] + l / 2.0, pos[2] + h / 2.0))
    return m


def aabb(mesh):
    lo, hi = mesh.bounds
    return [float(v) for v in np.concatenate([lo, hi])]


def safe_volume(mesh):
    if mesh is None or len(mesh.faces) == 0:
        return 0.0
    with np.errstate(divide='ignore', invalid='ignore'):
        try:
            return float(mesh.volume)
        except Exception:
            return 0.0


def xform(mesh, T):
    m = mesh.copy()
    m.apply_transform(T)
    return m


def rx(deg):
    return trimesh.transformations.rotation_matrix(math.radians(deg), [1, 0, 0])


def ry(deg):
    return trimesh.transformations.rotation_matrix(math.radians(deg), [0, 1, 0])


def sit_on_bed(mesh):
    m = mesh.copy()
    m.apply_translation((-m.bounds[0][0], -m.bounds[0][1], -m.bounds[0][2]))
    return m


def clean_part(mesh, name, notes):
    parts = mesh.split(only_watertight=False)
    if len(parts) <= 1:
        return mesh
    parts = sorted(parts, key=lambda p: abs(float(p.volume)), reverse=True)
    dropped = parts[1:]
    dv = sum(abs(float(p.volume)) for p in dropped)
    if dv > 1.0:
        notes.append(f"{name}: {len(dropped)} extra shells totalling {dv:.3f} mm3")
        return mesh
    notes.append(f"{name}: dropped {len(dropped)} degenerate flap(s) ({dv:.6f} mm3)")
    return parts[0]


def prepare_export(mesh):
    """Quantize to STL precision (float32), nudging coincident vertices apart so
    a downstream exact merge cannot rewire the topology, then re-check."""
    q = mesh.copy()
    q.vertices = np.round(q.vertices, 4)
    v = q.vertices
    try:
        groups = trimesh.grouping.group_rows(v, digits=4)
        for grp in groups:
            if len(grp) > 1:
                for k, idx in enumerate(grp[1:], start=1):
                    v[idx] += np.array([2.0e-5 * k, 6.0e-6 * k, 1.4e-5 * k])
    except Exception:
        pass
    q.vertices = v.astype(np.float32).astype(np.float64)
    q.process(validate=True)
    candidates = [q]
    d = q.copy()
    keep = d.nondegenerate_faces()
    if int(keep.sum()) != len(d.faces):
        d.update_faces(keep)
        d.process(validate=True)
        candidates.append(d)
    # Curved access holes can create valid short edges that four-decimal
    # quantization collapses. Preserve native STL float32 precision if that
    # coarser candidate fails, rather than trying to fill a manufactured hole.
    precise = mesh.copy()
    precise.vertices = precise.vertices.astype(np.float32).astype(np.float64)
    precise.process(validate=True)
    candidates.append(precise)
    for cand in candidates:
        try:
            if cand.is_watertight and cand.is_winding_consistent and cand.volume > 0:
                return cand
        except Exception:
            pass
    best = candidates[0]
    try:
        trimesh.repair.fill_holes(best)
        trimesh.repair.fix_normals(best)
        best.process(validate=True)
    except Exception:
        pass
    return best


def retry_io(fn, attempts=12, delay=0.25):
    """OneDrive and antivirus filters can transiently refuse a fresh file
    handle on Windows; retry a few times before giving up."""
    for k in range(attempts):
        try:
            return fn()
        except OSError:
            if k == attempts - 1:
                raise
            time.sleep(delay)


def probe_violation(shape, solids, pitch=2.0):
    if not isinstance(solids, (list, tuple)):
        solids = [solids]
    lo, hi = shape.bounds
    xs = np.arange(lo[0] + 0.2, hi[0], pitch)
    ys = np.arange(lo[1] + 0.2, hi[1], pitch)
    zs = np.arange(lo[2] + 0.2, hi[2], pitch)
    if not (len(xs) and len(ys) and len(zs)):
        return 0.0, 0.0, 0
    gx, gy, gz = np.meshgrid(xs, ys, zs, indexing='ij')
    pts = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])
    try:
        in_shape = shape.contains(pts)
    except Exception:
        return -1.0, -1.0, -1
    pts = pts[in_shape]
    if not len(pts):
        return 0.0, 0.0, 0
    inside = np.zeros(len(pts), bool)
    for s in solids:
        try:
            inside |= s.contains(pts)
        except Exception:
            pass
    hits = int(inside.sum())
    if not hits:
        return 0.0, 0.0, 0
    vol = hits * pitch ** 3
    depth = 0.0
    try:
        dmins = np.full(len(pts), np.inf)
        for s in solids:
            _cl, dist, _i = trimesh.proximity.closest_point(s, pts)
            dmins = np.minimum(dmins, dist)
        if inside.any():
            depth = float(np.max(dmins[inside]))
    except Exception:
        pass
    return vol, depth, hits


def mesh_report(mesh, file):
    m = mesh
    if not m.is_winding_consistent:
        trimesh.repair.fix_normals(m)
    return {
        "file": file,
        "bounds_mm": [round(float(v), 4) for v in np.asarray(m.bounds).reshape(-1)],
        "size_mm": [round(float(v), 4) for v in m.extents],
        "volume_mm3": round(float(m.volume), 3),
        "triangles": int(len(m.faces)),
        "watertight": bool(m.is_watertight),
        "winding_consistent": bool(m.is_winding_consistent),
        "components": int(m.body_count),
        "on_bed": bool(abs(m.bounds[0][2]) < 1e-4),
        "negative_z": bool(m.bounds[0][2] < -1e-4),
    }


def inches(mm):
    return f"{mm / 25.4:.2f}"


# ==========================================================================
# style model (flat tray + control deck)
# ==========================================================================

class Case:
    def __init__(self, profiles, style):
        self.g = profiles
        self.style = style
        self.p = profiles[style]
        self.wall = profiles['wall']
        self.floor = float(self.p.get('floor', profiles['floor_default']))
        self.lid_t = profiles['lid']
        self.r_out = self.p.get('corner_radius', profiles['corner_radius'])
        self.r_in = max(self.r_out - self.wall * 2.0, 0.8)
        self.w = float(self.p['width'])
        self.l = float(self.p['length'])
        self.hb = float(self.p['wall_height'])       # lid inner face z
        self.dash = self.p.get('dashboard')
        self.screw = profiles['screw']
        self.sw = profiles['switch']
        self.pl = dict(profiles['plunger'])
        self.pl.update(self.p.get('plunger', {}))

    # ---- surfaces --------------------------------------------------------
    def lid_top(self):
        return self.hb + self.lid_t

    def in_head(self, x, y):
        d = self.dash
        if not d or not d.get('head'):
            return False
        h = d['head']
        return (h['x'] - 1e-9 <= x <= h['x'] + h['width'] + 1e-9 and
                h['y'] - 1e-9 <= y <= h['y'] + h['length'] + 1e-9)

    def in_plateau(self, x, y):
        d = self.dash
        if not d or not d.get('plateau'):
            return False
        q = d['plateau']
        return (q['x'] - 1e-9 <= x <= q['x'] + q['width'] + 1e-9 and
                q['y'] - 1e-9 <= y <= q['y'] + q['length'] + 1e-9)

    def head_base(self):
        d = self.dash
        if not d or not d.get('head'):
            return self.lid_top()
        h = d['head']
        pl = d.get('plateau')
        if pl and pl['y'] - 1e-6 <= h['y'] <= pl['y'] + pl['length'] + 1e-6:
            return self.lid_top() + pl['height']
        return self.lid_top()

    def surface_z(self, x, y):
        """Control surface z at (x,y) in world coordinates."""
        d = self.dash
        if d:
            if self.in_head(x, y):
                h = d['head']
                return self.head_base() + (y - h['y']) * math.tan(math.radians(d['tilt_deg']))
            if self.in_plateau(x, y):
                return self.lid_top() + d['plateau']['height']
        return self.lid_top()

    def surface_tilt(self, x, y):
        if self.dash and self.in_head(x, y):
            return float(self.dash['tilt_deg'])
        return 0.0

    def frame(self, x, y):
        """Local control frame at (x,y): z normal to the local surface."""
        t = math.radians(self.surface_tilt(x, y))
        ca, sa = math.cos(t), math.sin(t)
        z = self.surface_z(x, y)
        return np.array([[1, 0, 0, x],
                         [0, ca, -sa, y],
                         [0, sa, ca, z],
                         [0, 0, 0, 1]], float)

    def local_depth(self, x, y):
        """Distance from the control surface down to the lid inner face."""
        return self.surface_z(x, y) - self.hb

    # ---- internals -------------------------------------------------------
    def comp(self, name):
        for c in self.p['components']:
            if c['name'] == name:
                return c
        raise KeyError(f"{self.style}: {name}")

    def cell(self):
        return self.comp(self.p['cell'])

    def board(self):
        return self.comp('xiao_nrf54l15')

    def buttons(self):
        return self.p.get('buttons', [])

    def switch_of(self, b):
        return self.comp(b['switch'])

    def mounts(self):
        return self.p.get('mounts', [])

    def board_rect(self):
        b = self.board()
        return (float(b['x']), float(b['y']),
                float(b['x']) + float(b['width']),
                float(b['y']) + float(b['length']))

    def oled_rect(self):
        if not self.p.get('oled'):
            return None
        o = self.comp('oled_display')
        return (float(o['x']), float(o['y']),
                float(o['x']) + float(o['width']),
                float(o['y']) + float(o['length']))

    def cell_rect(self):
        c = self.cell()
        return (float(c['x']), float(c['y']),
                float(c['x']) + float(c['width']),
                float(c['y']) + float(c['length']))

    def cell_h(self):
        key = self.p['cell']
        table = self.g['cells']
        for cand in (key, key.replace('_cell', '')):
            if cand in table:
                return float(table[cand]['height'])
        raise KeyError(key)

    def cell_z(self):
        return self.floor + self.g['deck']['foam']

    def deck_z(self):
        return self.cell_z() + self.cell_h() + self.g['deck']['foam']

    def deck_span(self):
        d = self.p['deck']
        return (float(d['y0']), float(d['y1']))

    def board_z(self):
        """(bottom, top) z of the XIAO PCB."""
        standoff=self.p['board'].get('standoff',self.g['board']['standoff'])
        z0 = self.deck_z() + self.g['deck']['thickness'] + float(standoff)
        return z0, z0 + float(self.g['board']['pcb_thickness'])

    def usb_center_z(self):
        z0, z1 = self.board_z()
        return z1 + float(self.g['board']['usb_center_above_pcb_top'])

    def charge_info(self):
        """(opening axis face, center along the wall, center z, opening w/h)."""
        cg = self.g['charge']
        ch = self.comp('charge_opening')
        face = self.p['charge']['face']
        ow, oh = cg['opening']
        if face in ('x_min', 'x_max'):
            return face, float(ch['y']) + ow / 2.0, self.usb_center_z(), ow, oh
        return face, float(ch['x']) + ow / 2.0, self.usb_center_z(), ow, oh

    def name(self, part):
        return f"{self.style}_{part}"

    def button_center(self, b):
        c = self.switch_of(b)
        return (float(c['x']) + float(c['width']) / 2.0,
                float(c['y']) + float(c['length']) / 2.0)

    def oled_params(self):
        o = self.p.get('oled') or {}
        base = dict(self.g[o.get('module', 'oled')])
        for key, val in o.items():
            if key not in ('x', 'y', 'module'):
                base[key] = val
        return base

    def well_params(self):
        w = dict(self.g['well'])
        w.update(self.p.get('well') or {})
        return w


# ==========================================================================
# body
# ==========================================================================

def charge_port_tool(C: Case, depth):
    face, mid, zc, ow, oh = C.charge_info()
    poly = rr_poly(ow, oh, 1.4)
    if face in ('y_min', 'y_max'):
        low, high = (-0.6, depth) if face == 'y_min' else (C.l - depth, C.l + 0.6)
        return prism_axis(poly, 'y', low, high, (mid - ow / 2, 0, zc - oh / 2))
    low, high = (-0.6, depth) if face == 'x_min' else (C.w - depth, C.w + 0.6)
    return prism_axis(poly, 'x', low, high, (0, mid - ow / 2, zc - oh / 2))


def charge_seat_tool(C: Case):
    face, mid, zc, _ow, _oh = C.charge_info()
    cg = C.g['charge']
    cw, ch, _ct = cg['cap_plate']
    depth = cg['seat_depth']
    if face in ('y_min', 'y_max'):
        low = -0.1 if face == 'y_min' else C.l - depth - 0.1
        return box(cw + 0.6, depth + 0.2, ch + 0.6,
                   (mid - cw / 2 - 0.3, low, zc - ch / 2 - 0.3))
    low = -0.1 if face == 'x_min' else C.w - depth - 0.1
    return box(depth + 0.2, cw + 0.6, ch + 0.6,
               (low, mid - cw / 2 - 0.3, zc - ch / 2 - 0.3))


def build_body(C: Case):
    g = C.g
    wall, floor, skirt = C.wall, C.floor, g['skirt']
    full = rr_poly(C.w, C.l, C.r_out)
    ins = rr_poly(C.w - 2 * skirt['inset'], C.l - 2 * skirt['inset'],
                  max(C.r_out - skirt['inset'], 1.0)) + skirt['inset']
    cloud = np.vstack([
        np.column_stack([ins, np.zeros(len(ins))]),
        np.column_stack([ins, np.full(len(ins), skirt['height'])]),
        np.column_stack([full, np.full(len(full), skirt['height'])]),
        np.column_stack([full, np.full(len(full), C.hb)]),
    ])
    body = trimesh.convex.convex_hull(cloud)
    cav_poly = rr_poly(C.w - 2 * wall, C.l - 2 * wall, C.r_in)
    cavity = prism_axis(cav_poly, 'z', floor, C.hb + 1.0, offset=(wall, wall, 0.0))
    body = dif(body, cavity)

    # Spread screw-head bearing loads locally rather than thickening the entire
    # floor. Tapered pads stay below the deck and leave the battery envelope free.
    reinforcement = C.screw.get('seat_reinforcement')
    seat_top = C.floor
    if reinforcement:
        seat_top += float(reinforcement['height'])
        angles = np.arange(SECTIONS) * 2.0 * math.pi / SECTIONS
        pads = []
        cx0, cy0, cx1, cy1 = C.cell_rect()
        clearance = float(reinforcement['cell_clearance'])
        exclusions = [box(cx1 - cx0 + 2 * clearance, cy1 - cy0 + 2 * clearance,
                          seat_top + 1, (cx0 - clearance, cy0 - clearance, -0.1))]
        if C.p.get('sidebar'):
            sc = C.comp(C.p['sidebar']['switch'])
            exclusions.append(box(float(sc['width']) + 2 * clearance,
                                  float(sc['length']) + 2 * clearance, seat_top + 1,
                                  (float(sc['x']) - clearance, float(sc['y']) - clearance, -0.1)))
        for sx, sy in C.p['fasteners']:
            rings = []
            for diameter, z in ((reinforcement['base_diameter'], C.floor - 0.1),
                                (reinforcement['top_diameter'], seat_top)):
                radius = float(diameter) / 2
                rings.append(np.column_stack([sx + radius * np.cos(angles),
                                              sy + radius * np.sin(angles),
                                              np.full(SECTIONS, z)]))
            pads.append(dif(trimesh.convex.convex_hull(np.vstack(rings)), exclusions))
        body = uni(body, *pads)

    # screw entries from the case back: head counterbore plus a through hole in the floor
    for (sx, sy) in C.p['fasteners']:
        body = dif(body, cyl_at(C.screw['clearance'], C.screw['head_depth'],
                                seat_top + 0.6, sx, sy))
        body = dif(body, cyl_at(C.screw['head_diameter'], -0.6, C.screw['head_depth'],
                                sx, sy))

    # deck ledges (narrow enough to clear the cell), cell bay rails
    d = g['deck']
    dy0, dy1 = C.deck_span()
    ledge = d['ledge_width']
    cx0, cy0, cx1, cy1 = C.cell_rect()
    margin = min(cx0 - C.wall, C.w - C.wall - cx1) - 0.1
    ledge = max(0.5, min(ledge, margin))
    top = C.deck_z()
    for xa, xb in ((wall - 0.4, wall + ledge), (C.w - wall - ledge, C.w - wall + 0.4)):
        body = uni(body, box(xb - xa, dy1 - dy0, top - floor, (xa, dy0, floor)))
    rw, rh = d['rail']
    body = uni(body,
               box(rw, (cy1 - cy0) + 2 * rw, rh, (cx0 - rw, cy0 - rw, floor)),
               box(rw, (cy1 - cy0) + 2 * rw, rh, (cx1, cy0 - rw, floor)),
               box((cx1 - cx0) + 2 * rw, rw, rh, (cx0 - rw, cy0 - rw, floor)),
               box((cx1 - cx0) + 2 * rw, rw, rh, (cx0 - rw, cy1, floor)))

    # switch pedestals: support the switch body above the floor or the cell top
    sw = C.sw
    for b in C.buttons():
        cx, cy = C.button_center(b)
        base = C.hb - (float(sw['body'][2]) + float(sw['actuator'][1]) +
                       float(C.pl['flange_height']))
        over_cell = (cx0 <= cx <= cx1 and cy0 <= cy <= cy1)
        z0 = (C.cell_z() + C.cell_h() + 0.02 if over_cell else C.floor - 0.2)
        h = base - z0
        if h > 0.1:
            wq, lq = float(sw['body'][0]) + 0.4, float(sw['body'][1]) + 0.4
            body = uni(body, rbox(wq, lq, h, 1.2, 0.6,
                                  (cx - wq / 2.0, cy - lq / 2.0, z0)))

    # charge / service slot through the wall (spans the lid seam, see build_lid)
    cg = g['charge']
    body = dif(body, [charge_port_tool(C, wall + 0.6), charge_seat_tool(C)])

    # side (Back / recall) button holes in a short wall
    sb = C.p.get('sidebar')
    if sb:
        pl = C.pl
        head = str(sb.get('head', 'back'))
        hd, hh = (pl['head_back'] if head == 'back' else
                  pl['head_numbered'] if head == 'numbered' else pl['head_plain'])
        sx, sz = float(sb['x']), float(sb['z'])
        face = sb.get('face', 'y_max')
        comp = C.comp(sb['switch'])
        wall_len = float(sb.get('wall_depth', 9.0))
        if face == 'y_max':
            wall_y = C.l - wall
            body = dif(body, [cyl(pl['lid_hole'], wall + 2.0, 'y', (sx, wall_y - 0.5, sz)),
                              cyl(hd + 2.0, 1.4, 'y', (sx, C.l - 0.7, sz))])
            body = dif(body, box(float(comp['width']), float(comp['length']) + 1.0,
                                 float(comp['width']),
                                 (float(comp['x']), wall_y - float(comp['length']),
                                  sz - float(comp['width']) / 2.0)))
        else:
            body = dif(body, [cyl(pl['lid_hole'], wall + 2.0, 'y', (sx, wall + 0.5, sz)),
                              cyl(hd + 2.0, 1.4, 'y', (sx, 0.7, sz))])
            body = dif(body, box(float(comp['width']), float(comp['length']) + 1.0,
                                 float(comp['width']),
                                 (float(comp['x']), wall,
                                  sz - float(comp['width']) / 2.0)))
        # Rear bearing for the side switch, joined to the floor and adjacent
        # face-switch pedestal. The pocket otherwise leaves an axial gap.
        stop_depth = float(sb.get('stop_depth',0.8))
        stop_top = sz + 0.5
        rear_y = float(comp['y']) + (float(comp['length']) if face == 'y_min' else 0)
        stop_y = rear_y if face == 'y_min' else rear_y - stop_depth
        body = uni(body, box(float(comp['width']), stop_depth, stop_top - floor + 0.2,
                             (float(comp['x']), stop_y, floor - 0.2)))

    # printed fixed NATO bars (two bars, lug arms, no metal)
    wb = g.get('watch_bars')
    if C.p.get('bars') and wb:
        bd = float(wb['bar'])
        stand = float(wb['standoff'])
        clear = float(wb['clear_width'])
        arm = float(wb['arm_width'])
        bite = float(wb['bite'])
        cx = C.w / 2.0
        ztop = stand + bd
        xa = cx - clear / 2.0 - arm
        xb = cx + clear / 2.0 + arm
        for yc, sgn in ((0.0, -1.0), (C.l, 1.0)):
            ybar = yc + sgn * (bd / 2.0 - bite)
            body = uni(body, cyl(bd, xb - xa, 'x', (cx, ybar, stand + bd / 2.0)))
            for ax in (xa, cx + clear / 2.0):
                ya, yb = sorted((yc - sgn * 2.0, ybar + sgn * bd / 2.0))
                body = uni(body, box(arm, yb - ya, ztop, (ax, ya, 0.0)))
            # Spread the outer lug roots into the shell without narrowing the
            # strap corridor. The lower ramp follows the existing 45-degree
            # shell bevel, so it does not create a horizontal floating ledge.
            radius = float(wb.get('root_gusset', 0))
            if radius:
                if not 0 < radius <= bd - bite:
                    raise ValueError('watch root gusset exceeds the existing lug span')
                for edge_x, away in ((xa, -1), (xb, 1)):
                    rings = []
                    for z, inset in ((0, C.g['skirt']['inset']),
                                     (C.g['skirt']['height'], 0), (ztop, 0)):
                        root_y = yc - sgn * inset
                        rings.append(np.array([
                            [edge_x, root_y, z],
                            [edge_x + away * radius, root_y, z],
                            [edge_x, root_y + sgn * radius, z]], dtype=float))
                    body = uni(body, trimesh.convex.convex_hull(np.vstack(rings)))
    relief = C.p.get('component_relief')
    if relief:
        import component_reliefs
        body, _, _, _ = component_reliefs.build(SimpleNamespace(**globals()), C, body,
                         float(relief['clearance']), float(relief['corner_radius']))
    return body


# ==========================================================================
# lid + control deck
# ==========================================================================

def dashboard_meshes(C: Case):
    """(plateau_mesh or None, head_mesh or None) in world coordinates."""
    d = C.dash
    if not d:
        return None, None
    plateau = None
    if d.get('plateau'):
        q = d['plateau']
        # top lands exactly on lid_top + height so the head base matches
        plateau = rbox(q['width'], q['length'], q['height'] + 0.3, 3.0, 0.6,
                       (q['x'], q['y'], C.lid_top() - 0.3))
    head = None
    if d.get('head'):
        h = d['head']
        base = C.head_base()
        rise = float(h['length']) * math.tan(math.radians(d['tilt_deg']))
        # dip 0.6 below the base so the head fuses with the plate/plateau
        poly = np.array([[h['y'], base - 0.6], [h['y'] + h['length'], base - 0.6],
                         [h['y'] + h['length'], base + rise], [h['y'], base]])
        head = prism_axis(poly, 'x', h['x'], h['x'] + h['width'])
        # round the ends to the case outline
        clip = prism_axis(rr_poly(C.w, C.l, C.r_out), 'z', base - 2.0, base + rise + 2.0)
        head = inter(head, clip)
    return plateau, head


def header_rects(C: Case):
    """(x0, y0, x1, y1) rectangles of the pre-soldered header strips on the board top."""
    bd = C.g['board']
    hdr = bd.get('header') or {}
    if not hdr:
        return []
    bx0, by0, bx1, by1 = C.board_rect()
    pins = int(hdr['pins'])
    pitch = float(hdr['pitch'])
    hw = float(hdr['width'])
    sl = (pins - 1) * pitch + pitch
    if (bx1 - bx0) >= (by1 - by0):
        sx0 = (bx0 + bx1 - sl) / 2.0
        return [(sx0, by0, sx0 + sl, by0 + hw), (sx0, by1 - hw, sx0 + sl, by1)]
    sy0 = (by0 + by1 - sl) / 2.0
    return [(bx0, sy0, bx0 + hw, sy0 + sl), (bx1 - hw, sy0, bx1, sy0 + sl)]


def board_keepouts(C: Case):
    """(x0, y0, x1, y1) rectangles on the board top that the lid pads must clear."""
    g = C.g
    bd = g['board']
    bx0, by0, bx1, by1 = C.board_rect()
    rects = list(header_rects(C))
    face = C.p['charge']['face']
    cxm = (bx0 + bx1) / 2.0
    cym = (by0 + by1) / 2.0
    if bd.get('use_manufacturer_usb'):
        import usb_reference
        (x0,y0),(x1,y1)=usb_reference.bounds(C)
        rects.append((x0,y0,x1,y1))
    elif face == 'y_max':
        rects.append((cxm - 4.0, C.l - 6.0, cxm + 4.0, C.l - 2.5))
    elif face == 'y_min':
        rects.append((cxm - 4.0, 2.5, cxm + 4.0, 6.0))
    elif face == 'x_max':
        rects.append((C.w - 6.0, cym - 4.0, C.w - 2.5, cym + 4.0))
    else:
        rects.append((2.5, cym - 4.0, 6.0, cym + 4.0))
    rects.append((bx0 + 6.8, by0 + 6.8,
                  bx0 + 6.8 + max(bx1 - bx0 - 13.6, 4.0),
                  by0 + 6.8 + max(by1 - by0 - 13.6, 4.0)))
    return rects


def build_lid(C: Case):
    g = C.g
    wall = C.wall
    lip = g['lip']
    plate = rbox(C.w, C.l, C.lid_t, C.r_out, 0.9, (0.0, 0.0, C.hb))
    lid = plate

    # inset lip ring
    lo = lip['clearance']
    lip_out = rr_poly(C.w - 2 * wall - 2 * lo, C.l - 2 * wall - 2 * lo,
                      max(C.r_in - lo, 0.5)) + (wall + lo)
    lip_in = rr_poly(C.w - 2 * wall - 2 * lo - 2 * lip['thickness'],
                     C.l - 2 * wall - 2 * lo - 2 * lip['thickness'],
                     max(C.r_in - lo - lip['thickness'], 0.5)) + (wall + lo + lip['thickness'])
    ring = dif(prism_axis(lip_out, 'z', C.hb - lip['height'], C.hb + 0.4),
               prism_axis(lip_in, 'z', C.hb - lip['height'] - 0.5, C.hb + 0.5))
    lid = uni(lid, ring)

    # relieve the lip ring where the pre-soldered header strips pass
    for (x0, y0, x1, y1) in header_rects(C):
        lid = dif(lid, box(x1 - x0 + 0.2, y1 - y0 + 0.2, lip['height'] + 0.1,
                           (x0 - 0.1, y0 - 0.1, C.hb - lip['height'] - 0.1)))

    # control deck
    plateau, head = dashboard_meshes(C)
    lid = uni(lid, plateau, head)

    # blind pilot bosses on the inner face (screws enter from the case back)
    b0 = C.deck_z() + C.g['deck']['thickness'] + float(C.screw['boss_gap'])
    for (sx, sy) in C.p['fasteners']:
        lid = uni(lid, cyl_at(C.screw['boss_diameter'], b0, C.hb + 0.1, sx, sy))
        lid = dif(lid, cyl_at(C.screw['pilot'], b0 - 0.6,
                              b0 + C.screw['pilot_depth'], sx, sy))

    # OLED window + seat in the sloped head
    if C.p.get('oled'):
        oled = C.oled_params()
        ox0, oy0, ox1, oy1 = C.oled_rect()
        ccx, ccy = (ox0 + ox1) / 2.0, (oy0 + oy1) / 2.0
        F = C.frame(ccx, ccy)
        bw, bl = oled['window']
        win = box(bw, bl, 80.0, (-bw / 2.0, -bl / 2.0, -40.0))
        lid = dif(lid, xform(win, F))
        seat_d = float(oled['seat_depth'])
        sw_, sl_ = ox1 - ox0 + 0.8, oy1 - oy0 + 0.8
        drop = float(oled['height']) + 2.0
        seat = box(sw_, sl_, seat_d + drop,
                   (-sw_ / 2.0, -sl_ / 2.0, -seat_d - (seat_d + drop)))
        lid = dif(lid, xform(seat, F))

    # buttons: well, plunger hole, holder frame on the inner side
    for b in C.buttons():
        cx, cy = C.button_center(b)
        F = C.frame(cx, cy)
        L = C.local_depth(cx, cy)
        wp = C.well_params()
        well_d, well_h = float(wp['diameter']), float(wp['depth'])
        well = cyl(well_d, well_h + 2.0, 'z', (0, 0, (2.0 - well_h) / 2.0))
        lid = dif(lid, xform(well, F))
        # plunger hole from the well floor down to the lid inner face
        hole_h = L - well_h
        hole = cyl(C.pl['lid_hole'], hole_h + 0.4, 'z',
                   (0, 0, -(well_h + L) / 2.0))
        lid = dif(lid, xform(hole, F))
        ci = float(C.sw['collar_interior'])
        cw = float(C.sw['collar_wall'])
        cr = float(C.sw.get('collar_corner', 1.0))
        cdep = (float(C.sw['body'][2]) + float(C.sw['actuator'][1]) +
                float(C.pl['flange_height']))
        frame = dif(rbox(ci + 2 * cw, ci + 2 * cw, cdep + 0.25, cr + cw, 0.5,
                         (-(ci + 2 * cw) / 2.0, -(ci + 2 * cw) / 2.0, -L - cdep - 0.15)),
                    rbox(ci, ci, cdep + 0.65, cr, 0.4,
                         (-ci / 2.0, -ci / 2.0, -L - cdep - 0.5)))
        lid = uni(lid, xform(frame, F))

    # relieve a collar wall where a taller side-entry switch reaches into it
    if C.p.get('sidebar'):
        sbp = C.p['sidebar']
        sbc = C.comp(sbp['switch'])
        ci = float(C.sw['collar_interior'])
        cw = float(C.sw['collar_wall'])
        swx0 = float(sbc['x'])
        swx1 = swx0 + float(sbc['width'])
        swy0 = float(sbc['y'])
        swy1 = swy0 + float(sbc['length'])
        top = float(sbp['z']) + float(sbc['width']) / 2.0
        bot = C.hb - (float(C.sw['body'][2]) + float(C.sw['actuator'][1]) +
                      float(C.pl['flange_height'])) - 0.2
        for b in C.buttons():
            cx, cy = C.button_center(b)
            if sbp.get('face', 'y_max') == 'y_min':
                w0, w1 = cy - ci / 2.0 - cw, cy - ci / 2.0
            else:
                w0, w1 = cy + ci / 2.0, cy + ci / 2.0 + cw
            if w1 < swy0 or w0 > swy1:
                continue
            x0 = max(swx0, cx - ci / 2.0 - cw)
            x1 = min(swx1, cx + ci / 2.0 + cw)
            lid = dif(lid, box(x1 - x0 + 0.1, (w1 - w0) + 0.1, top - bot + 0.1,
                               (x0 - 0.05, w0 - 0.05, bot)))

    # board pads on the inner face: nearest clear spot to each nominal corner,
    # keeping clear of the header strips, USB shell, component stack and bosses
    bx0, by0, bx1, by1 = C.board_rect()
    so = float(g['board']['standoff'])
    pad_r = 1.7
    keepouts = board_keepouts(C)

    def pad_score(qx, qy):
        if qx - pad_r < bx0 or qx + pad_r > bx1 or qy - pad_r < by0 or qy + pad_r > by1:
            return None
        pen = 0.0
        for (x0, y0, x1, y1) in keepouts:
            dx = max(x0 - qx, 0.0, qx - x1)
            dy = max(y0 - qy, 0.0, qy - y1)
            pen = max(pen, pad_r + 0.2 - math.hypot(dx, dy))
        for (fx, fy) in C.p['fasteners']:
            pen = max(pen, 6.5 - math.hypot(qx - fx, qy - fy))
        return pen

    pads = []
    for (nx, ny) in ((bx0 + pad_r, by0 + pad_r), (bx1 - pad_r, by0 + pad_r),
                     (bx0 + pad_r, by1 - pad_r), (bx1 - pad_r, by1 - pad_r)):
        best = None
        for i in range(-32, 33):
            for j in range(-32, 33):
                qx, qy = nx + i * 0.5, ny + j * 0.5
                pen = pad_score(qx, qy)
                if pen is None:
                    continue
                key = (round(max(pen, 0.0), 2), i * i + j * j)
                if best is None or key < best[0]:
                    best = (key, qx, qy)
        pads.append((best[1], best[2]))
    for (qx, qy) in pads:
        if C.g['board'].get('mounting')!='deck-posts':
            lid = uni(lid, cyl_at(3.4, C.board_z()[1], C.hb + 0.1, qx, qy))

    # hood bar along the high edge of the head
    if C.p.get('oled') and C.dash and C.dash.get('head'):
        bz = g['bezel']
        h = C.dash['head']
        ytop = h['y'] + h['length'] - bz['hood'] / 2.0
        F = C.frame(h['x'] + h['width'] / 2.0, ytop)
        hood = box(h['width'] - 10.0, bz['hood'], bz['hood_height'] + 0.15,
                   (-(h['width'] - 10.0) / 2.0, -bz['hood'] / 2.0, -0.1))
        lid = uni(lid, xform(hood, F))

    # Share the complete port and flange seat with the body: a separate short
    # lid notch can obstruct both the rigid flange and the upper plug rim.
    face, mid, zc, ow, oh = C.charge_info()
    lid = dif(lid, [charge_port_tool(C, C.wall + 2.6), charge_seat_tool(C)])

    # pocket over the USB shell on the inner face (only if the shell pokes past)
    face_ch = C.p['charge']['face']
    poke = (C.board_z()[1] + float(g['board']['usb_shell_height']) + 0.15) - C.hb
    pocket_d = min(max(poke + 0.25, 0.0), C.lid_t - 0.6)
    if (C.board_z()[1] + float(g['board']['usb_shell_height']) + 0.1) > (C.hb - g['lip']['height']):
        sh_h = pocket_d + 1.75
        if g['board'].get('use_manufacturer_usb'):
            import usb_reference
            (x0,y0),(x1,y1)=usb_reference.bounds(C)
            z0=C.hb-g['lip']['height']-.1
            z1=min(C.board_z()[1]+.1+3.25+.15,C.lid_top()-.6)
            shell_pocket=box(x1-x0+.3,y1-y0+.3,z1-z0,(x0-.15,y0-.15,z0))
        elif face_ch == 'y_max':
            shell_pocket = box(8.4, 5.5, sh_h, (mid - 4.2, C.l - 6.0, C.hb - 1.65))
        elif face_ch == 'y_min':
            shell_pocket = box(8.4, 5.5, sh_h, (mid - 4.2, 0.5, C.hb - 1.65))
        elif face_ch == 'x_max':
            shell_pocket = box(5.5, 8.4, sh_h, (C.w - 6.0, mid - 4.2, C.hb - 1.65))
        else:
            shell_pocket = box(5.5, 8.4, sh_h, (0.5, mid - 4.2, C.hb - 1.65))
        lid = dif(lid, shell_pocket)

    # pitcher guard ring on the flat face
    if C.p.get('guard'):
        gd = C.p['guard']
        gx, gy = float(gd['x']), float(gd['y'])
        gd_d, gd_h = float(gd['diameter']), float(gd['height'])
        wd, _wdep = float(gd['well_diameter']), float(gd['well_depth'])
        ring = dif(cyl(gd_d, gd_h + 0.2, 'z', (gx, gy, C.lid_top() + (gd_h - 0.2) / 2.0)),
                   cyl(gd_d - 2.4, gd_h + 0.6, 'z', (gx, gy, C.lid_top() + (gd_h - 0.2) / 2.0)))
        well = cyl(wd, gd_h + 2.0, 'z', (gx, gy, C.lid_top() + (2.0 - gd_h) / 2.0 - 0.0))
        lid = uni(lid, ring)
        lid = dif(lid, well)
    return lid


def build_deck(C: Case):
    d = C.g['deck']
    t = d['thickness']
    dy0, dy1 = C.deck_span()
    clearance = float(d.get('edge_clearance', 0.2))
    x0, x1 = C.wall + clearance, C.w - C.wall - clearance
    z0 = C.deck_z()
    # Match the actual rounded tray cavity, including its end corners.
    # A small edge bevel preserves a flat bearing land on the narrow ledges.
    plate = rbox(x1 - x0, dy1 - dy0, t, C.r_in, 0.1, (x0, dy0, z0))
    cavity_outline = rr_poly(C.w - 2 * (C.wall + clearance),
                             C.l - 2 * (C.wall + clearance),
                             max(C.r_in - clearance, 0.5)) + (C.wall + clearance)
    plate = inter(plate, prism_axis(cavity_outline, 'z', z0 - 1, z0 + t + 1))
    tools = []
    for (sx, sy) in C.p['fasteners']:
        tools.append(cyl(C.screw['clearance'] + 0.6, t + 6.0, 'z',
                         (sx, sy, z0 + t / 2.0)))
    pn = d['pull_notch']
    cyc = (C.cell_rect()[1] + C.cell_rect()[3]) / 2.0
    if C.g['board'].get('mounting')=='deck-posts':
        end=C.p['deck']['access_end']
        tools.append(box(12,4,t+6,((C.w-12)/2,dy0 if end=='front' else dy1-4,z0-3)))
    else:
        tools.append(box(pn[0], pn[1], t + 6.0, (x1 - pn[0], cyc - pn[1] / 2.0, z0 - 3.0)))
    cg = C.g['charge']
    face, mid, zc, ow, oh = C.charge_info()
    if C.g['board'].get('mounting')=='deck-posts':
        # Reserve the actual assembled cap with 0.3 mm allowance. Its bottom
        # is above these decks; a full-depth 12 mm notch was unnecessary.
        cap=xform(build_charge_cap(C),charge_cap_matrix(C))
        lo,hi=cap.bounds[0]-.3,cap.bounds[1]+.3
        tools.append(box(*(hi-lo),lo))
    elif face in ('y_max', 'y_min'):
        tools.append(box(ow + 5.0, 12.0, t + 6.0, (mid - (ow + 5.0) / 2.0,
                                                   (0.0 if face == 'y_min' else C.l - 12.0),
                                                   z0 - 3.0)))
    else:
        tools.append(box(12.0, ow + 5.0, t + 6.0, ((0.0 if face == 'x_min' else C.w - 12.0),
                                                   mid - (ow + 5.0) / 2.0, z0 - 3.0)))
    for b in C.buttons():
        cx, cy = C.button_center(b)
        ci = C.sw['collar_interior'] + 2 * C.sw['collar_wall'] + 0.2
        tools.append(box(ci, ci, t + 6.0, (cx - ci / 2.0, cy - ci / 2.0, z0 - 3.0)))
    if C.p.get('sidebar'):
        sbp = C.p['sidebar']
        sbc = C.comp(sbp['switch'])
        cut_w = float(sbc['width']) + 4.0
        cut_d = float(sbc['length']) + 4.0
        cut_y = (C.wall - 2.0 if sbp.get('face', 'y_max') == 'y_min'
                 else C.l - C.wall - cut_d + 2.0)
        cut_x=float(sbc['x'])-2.0 if C.g['board'].get('mounting')=='deck-posts' else float(sbp['x'])-2.0
        tools.append(box(cut_w, cut_d, t + 6.0,
                         (cut_x, cut_y, z0 - 3.0)))
    deck=dif(plate,tools)
    if C.p['deck'].get('lightening'):
        import deck_windows
        deck=deck_windows.apply(SimpleNamespace(**globals()),C,deck)
    if C.g['board'].get('mounting')=='deck-posts':
        import board_supports
        deck=board_supports.add(SimpleNamespace(**globals()),C,deck)
    return deck


def build_charge_cap(C: Case):
    cg = C.g['charge']
    cw, chh, ct = cg['cap_plate']
    ow, oh = cg['opening']
    pd, pw = cg['plug_depth'], cg['plug_wall']
    plate = rbox(cw, chh, ct, 2.0, 0.6, (-cw / 2.0, -chh / 2.0, 0.0))
    fit = float(cg.get('plug_interference', 0.3))
    ow2, oh2 = ow + 2 * fit, oh + 2 * fit
    radius = 1.4 + fit
    outer = rbox(ow2, oh2, pd, radius, min(0.4, pd / 2 - 0.01),
                 (-ow2 / 2.0, -oh2 / 2.0, ct - 0.1))
    iw, ih = ow2 - 2 * pw + 0.02, oh2 - 2 * pw + 0.02
    inner = prism_axis(rr_poly(iw, ih, max(radius - pw, 0.2)), 'z', ct - 0.6, ct + pd + 0.5,
                       (-iw / 2, -ih / 2, 0))
    return uni(plate, dif(outer, inner))


def charge_cap_wall_matrix(C: Case):
    """Align the print frame to the outer wall plane."""
    face, mid, zc, ow, oh = C.charge_info()
    cw, chh, ct = C.g['charge']['cap_plate']
    if face == 'x_max':
        return np.array([[0, 0, -1, C.w],
                         [-1, 0, 0, mid],
                         [0, 1, 0, zc],
                         [0, 0, 0, 1]], float)
    if face == 'x_min':
        return np.array([[0, 0, 1, 0.0],
                         [1, 0, 0, mid],
                         [0, 1, 0, zc],
                         [0, 0, 0, 1]], float)
    if face == 'y_max':
        return np.array([[1, 0, 0, mid],
                         [0, 0, -1, C.l],
                         [0, 1, 0, zc],
                         [0, 0, 0, 1]], float)
    return np.array([[1, 0, 0, mid],
                     [0, 0, 1, 0.0],
                     [0, -1, 0, zc],
                     [0, 0, 0, 1]], float)


def charge_cap_matrix(C: Case):
    """Seat the flange partly into the wall, leaving an exposed removal edge."""
    matrix = charge_cap_wall_matrix(C)
    outward = C.g['charge']['cap_plate'][2] - C.g['charge']['seat_depth']
    matrix[:3, 3] -= matrix[:3, 2] * outward
    return matrix


def build_carrier(C: Case, mount):
    g = C.g['carrier']
    plate_t = g['plate']
    carrier = rbox(C.w, C.l, plate_t, C.r_out, 0.8, (0.0, 0.0, -plate_t))
    strap = float(mount['strap_width'])
    loop_h, wall, pad = g['loop_height'], g['loop_wall'], g['inset']
    for (cx, cy) in mount['centers']:
        if mount.get('layout') == 'in_line_y':
            lx0, lx1 = C.wall + 1.0, C.w - C.wall - 1.0
        else:
            ll = float(mount.get('loop_length', 12.0))
            lx0, lx1 = float(cx) - ll / 2.0, float(cx) + ll / 2.0
        # strap is the clear tunnel width, not the outside loop width.
        ly0 = float(cy) - (strap + 2 * pad + 2 * wall) / 2.0
        ly1 = float(cy) + (strap + 2 * pad + 2 * wall) / 2.0
        outer = rbox(lx1 - lx0, ly1 - ly0, loop_h, 2.0, 0.5,
                     (lx0, ly0, -plate_t - loop_h + 0.1))
        inner = box(lx1 - lx0 + 2.0, ly1 - ly0 - 2 * wall, loop_h - 1.2,
                    (lx0 - 1.0, ly0 + wall, -plate_t - loop_h + 1.3))
        carrier = uni(carrier, dif(outer, inner))
        rise = float(g.get('junction_rise', 0))
        if rise:
            # Extend the loop rails through the plate's lower bevel. A 0.1 mm
            # overlap plus two chamfers otherwise leaves a narrow V-groove
            # beside the strap mouth. Keep the original tunnel rectangle open.
            if not 0.8 <= rise <= plate_t - 0.5:
                raise ValueError('carrier junction landing must cover the plate bevel')
            landing = rbox(lx1 - lx0, ly1 - ly0, rise + 0.5, 2.0, 0.1,
                           (lx0, ly0, -plate_t - 0.5))
            opening = box(lx1 - lx0 + 2.0, ly1 - ly0 - 2 * wall, rise + 0.9,
                          (lx0 - 1.0, ly0 + wall, -plate_t - 0.7))
            carrier = uni(carrier, dif(landing, opening))
    lightening = g.get('lightening')
    if lightening:
        # Windows stay inside the strap tunnels, leaving continuous perimeter
        # rails, three-millimetre webs and full landing pads beneath screw heads.
        edge, rib = float(lightening['edge']), float(lightening['rib'])
        windows = []
        head_keepouts = [cyl(C.screw['head_diameter'] + 2 * lightening['head_margin'],
                             plate_t + 1, 'z', (sx, sy, -plate_t / 2))
                         for sx, sy in C.p['fasteners']]
        for cx, cy in mount['centers']:
            if mount.get('layout') == 'in_line_y':
                xa, xb = C.wall + 1 + edge, C.w - C.wall - 1 - edge
            else:
                length = float(mount.get('loop_length', 12))
                xa, xb = float(cx) - length / 2 + edge, float(cx) + length / 2 - edge
            ya = float(cy) - (strap + 2 * pad) / 2 + edge
            yb = float(cy) + (strap + 2 * pad) / 2 - edge
            nx = max(1, math.ceil((xb - xa + rib) / (lightening['max_width'] + rib)))
            ny = max(1, math.ceil((yb - ya + rib) / (lightening['max_length'] + rib)))
            width, length = (xb - xa - (nx - 1) * rib) / nx, (yb - ya - (ny - 1) * rib) / ny
            if min(width, length) < 2.0:
                raise ValueError(f'{C.style}: carrier lightening leaves an unprintable window')
            for ix in range(nx):
                for iy in range(ny):
                    poly = rr_poly(width, length, min(2.0, width / 2 - 0.1, length / 2 - 0.1))
                    tool = prism_axis(poly, 'z', -plate_t - 0.2, 0.2,
                                      (xa + ix * (width + rib), ya + iy * (length + rib), 0))
                    windows.append(dif(tool, head_keepouts))
        carrier = dif(carrier, windows)
    if g.get('retention'):
        # Reuse the case fasteners to clamp the carrier to the body and lid.
        # Recess heads flush with the tunnel ceiling; open the lower bridge
        # skin for screw insertion and driver access without cutting its walls.
        if plate_t - C.screw['head_depth'] < 1.0:
            raise ValueError(f'{C.style}: carrier screw bearing is less than 1 mm')
        for sx, sy in C.p['fasteners']:
            carrier = dif(carrier, [
                cyl_at(C.screw['clearance'], -plate_t - 0.1, 0.5, sx, sy),
                cyl_at(C.screw['head_diameter'], -plate_t - 0.1,
                       -plate_t + C.screw['head_depth'], sx, sy),
                cyl_at(g['retention']['access_diameter'], -plate_t - loop_h - 1,
                       -plate_t + 0.05, sx, sy)])
    return carrier


# ==========================================================================
# controls
# ==========================================================================

DIGITS = {
    '1': ['010', '110', '010', '010', '111'],
    '2': ['111', '001', '111', '100', '111'],
    '3': ['111', '001', '111', '001', '111'],
    '4': ['101', '101', '111', '001', '001'],
}


def plunger_head_sizes(C, b):
    head = str(b.get('head', 'plain'))
    pl = C.pl
    if head == 'numbered':
        return head, pl['head_numbered'][0], pl['head_numbered'][1]
    if head == 'back':
        return head, pl['head_back'][0], pl['head_back'][1]
    return head, pl['head_plain'][0], pl['head_plain'][1]


def build_plunger_solid_local(C, b):
    """Control-surface-local frame: +z outward, with free inward stroke."""
    head, hd, hh = plunger_head_sizes(C, b)
    pl = C.pl
    cx, cy = C.button_center(b)
    L = C.local_depth(cx, cy)
    well_d = float(C.well_params()['depth'])
    z_top = -float(pl.get('face_recess', well_d - hh))
    z_head_bot = z_top - hh
    fl_top = -L
    fl_bot = fl_top - pl['flange_height']
    shaft = uni(cyl_at(pl['shaft'], fl_bot, z_head_bot + 0.2, 0, 0),
                cyl(pl['flange'], pl['flange_height'], 'z',
                    (0, 0, (fl_top + fl_bot) / 2.0)))
    m = uni(cyl(hd, hh, 'z', (0, 0, z_top - hh / 2.0)), shaft)
    if head == 'numbered':
        dg = pl['digit']
        if dg.get('inlay'):
            pocket = numeral_local(C, b, -dg['slot_depth'], 1.0,
                                   dg['pocket_clearance'])
            pocket.apply_translation((0, 0, z_top))
            return dif(m, pocket)
        pix = DIGITS.get(str(b.get('digit', '1')), DIGITS['1'])
        cell = dg['cell']
        ox = (len(pix[0]) - 1) * cell / 2.0
        oy = (len(pix) - 1) * cell / 2.0
        for r, row in enumerate(pix):
            for c, ch in enumerate(row):
                if ch == '1':
                    t = box(cell * 0.8, cell * 0.8, dg['slot_depth'] + 0.8,
                            (-cell * 0.4 + (c * cell - ox),
                             -cell * 0.4 + (oy - r * cell), z_top - dg['slot_depth']))
                    m = dif(m, t)
    return m


def split_button_local(C, solid, L, head_bottom):
    """Two rigid parts with an axial assembly path through the guide."""
    j = C.pl['joint']
    fl_bot = -L - C.pl['flange_height']
    stem = uni(cyl_at(j['post_diameter'], fl_bot, head_bottom, 0, 0),
               cyl_at(C.pl['flange'], fl_bot, -L, 0, 0))
    head = inter(solid, box(40, 40, 10, (-20, -20, head_bottom)))
    sleeve_bottom = head_bottom - j['engagement']
    head = uni(head, cyl_at(j['sleeve_diameter'], sleeve_bottom, head_bottom + 0.1, 0, 0))
    head = dif(head, cyl_at(j['socket_diameter'], sleeve_bottom - 0.1, head_bottom, 0, 0))
    return stem, head


def build_plunger_parts_local(C, b):
    solid = build_plunger_solid_local(C, b)
    if not C.pl.get('joint'):
        return solid, None
    _head, _hd, hh = plunger_head_sizes(C, b)
    recess = float(C.pl.get('face_recess', C.well_params()['depth'] - hh))
    return split_button_local(C, solid, C.local_depth(*C.button_center(b)), -recess - hh)


def build_plunger_local(C, b):
    return uni(*build_plunger_parts_local(C, b))


def build_label_local(C, b):
    dg = C.pl['digit']
    if dg.get('inlay'):
        return numeral_local(C, b, 0, dg['slot_depth'] - dg['bottom_clearance'])
    pix = DIGITS.get(str(b.get('digit', '1')), DIGITS['1'])
    cell = dg['cell']
    cl = dg['label_clearance']
    lt = dg['label_thickness']
    base_h = 0.22
    base = box(3 * cell, 5 * cell, base_h, (-1.5 * cell, -2.5 * cell, 0.0))
    parts = [base]
    ox = (len(pix[0]) - 1) * cell / 2.0
    oy = (len(pix) - 1) * cell / 2.0
    for r, row in enumerate(pix):
        for c, ch in enumerate(row):
            if ch == '1':
                sz = cell - 2 * cl
                parts.append(box(sz, sz, lt, (c * cell - ox - sz / 2.0,
                                              oy - r * cell - sz / 2.0, base_h - 0.02)))
    return uni(*parts)


def numeral_local(C, b, z0, z1, clearance=0):
    """A connected, constant-section numeral without a covering backplate."""
    dg = C.pl['digit']
    pix = DIGITS[str(b['digit'])]
    cell = float(dg['cell'])
    width = cell + 2 * clearance
    ox, oy = (len(pix[0]) - 1) * cell / 2, (len(pix) - 1) * cell / 2
    return uni(*[box(width, width, z1 - z0,
                     (c * cell - ox - width / 2, oy - r * cell - width / 2, z0))
                 for r, row in enumerate(pix) for c, value in enumerate(row) if value == '1'])


def label_matrix(C, b):
    F = C.frame(*C.button_center(b))
    if C.pl['digit'].get('inlay'):
        _head, _hd, hh = plunger_head_sizes(C, b)
        recess = float(C.pl.get('face_recess', C.well_params()['depth'] - hh))
        thickness = C.pl['digit']['slot_depth'] - C.pl['digit']['bottom_clearance']
        offset = np.eye(4)
        offset[2, 3] = -recess - thickness
        return F @ offset
    return F


def build_bezel_local(C):
    g = C.g
    bz, oled = g['bezel'], C.oled_params()
    bw, bl = oled['window']
    # no window insert: the opening hugs the lid's window with a 0.3 reveal
    ri = (bw + 0.6, bl + 0.6)
    ro = (ri[0] + 2 * bz['frame'], ri[1] + 2 * bz['frame'])
    outer = rbox(ro[0], ro[1], bz['height'], 2.0, 0.6, (-ro[0] / 2.0, -ro[1] / 2.0, 0.0))
    inner = rbox(ri[0], ri[1], bz['height'] + 1.0, 1.4, 0.4,
                 (-ri[0] / 2.0, -ri[1] / 2.0, -0.4))
    return dif(outer, inner)


def bezel_matrix(C):
    ox0, oy0, ox1, oy1 = C.oled_rect()
    return C.frame((ox0 + ox1) / 2.0, (oy0 + oy1) / 2.0)


def build_side_plunger_solid_local(C):
    pl = C.pl
    sb = C.p.get('sidebar') or {}
    head = str(sb.get('head', 'back'))
    hd, hh = (pl['head_back'] if head == 'back' else
              pl['head_numbered'] if head == 'numbered' else pl['head_plain'])
    fd, fh = pl['flange'], pl['flange_height']
    L = C.l
    y_head_out = L - float(pl.get('face_recess', 0.2))
    y_head_in = y_head_out - hh
    y_fl_top = L - C.wall - 0.0
    y_fl_bot = y_fl_top - fh
    shaft = uni(cyl(pl['shaft'], y_head_in + 0.2 - y_fl_bot, 'y',
                    (0, (y_head_in + 0.2 + y_fl_bot) / 2.0, 0)),
                cyl(fd, fh, 'y', (0, (y_fl_top + y_fl_bot) / 2.0, 0)))
    return uni(cyl(hd, hh, 'y', (0, y_head_out - hh / 2.0, 0)), shaft)


def build_side_plunger_parts_local(C):
    solid = build_side_plunger_solid_local(C)
    if not C.pl.get('joint'):
        return solid, None
    N = rx(90)
    N[2, 3] = -C.l
    hh = C.pl['head_back'][1]
    parts = split_button_local(C, xform(solid, N), C.wall,
                               -float(C.pl.get('face_recess', 0.2)) - hh)
    return tuple(xform(m, np.linalg.inv(N)) for m in parts)


def build_side_plunger_local(C):
    return uni(*build_side_plunger_parts_local(C))


def side_plunger_matrix(C):
    sb = C.p['sidebar']
    M = np.eye(4)
    M[0, 3] = float(sb['x'])
    M[2, 3] = float(sb['z'])
    if sb.get('face', 'y_max') == 'y_min':
        T = np.eye(4)
        T[1, 3] = C.l
        return M @ T @ rx(180)
    return M


def build_fit_coupon(profiles):
    fc = profiles['fit_coupon']
    w, l, t = fc['size']
    plate = rbox(w, l, t, 3.0, 0.6)
    tools = []
    for d, (cx, cy) in zip(fc['holes'], fc['hole_centers']):
        tools.append(cyl(d, t + 2.0, 'z', (cx, cy, t / 2.0)))
    if fc.get('strap_gauges'):
        for gauge in fc['strap_gauges']:
            s, th = gauge['width'], gauge['height']
            cx, cy = gauge['center']
            tools.append(prism_axis(rr_poly(s, th, 0.1), 'z', -0.5, t + 0.5,
                                    (cx - s / 2, cy - th / 2, 0)))
    else:
        for s, (cx, cy) in zip(fc['slots'], fc['slot_centers']):
            th = fc['slot_thickness']
            tools.append(prism_axis(rr_poly(s, th, th / 2.0), 'z', -0.5, t + 0.5,
                                    offset=(cx - s / 2.0, cy - th / 2.0, 0.0)))
    if fc.get('head_gauge'):
        gauge = fc['head_gauge']
        cx, cy = gauge['center']
        sw = profiles['screw']
        if gauge['floor'] - sw['head_depth'] < 1:
            raise ValueError('coupon screw bearing must be at least 1 mm')
        pw = gauge['pocket_width']
        tools.extend([box(pw, pw, t + 1, (cx - pw / 2, cy - pw / 2, gauge['floor'])),
                      cyl_at(sw['clearance'], -0.5, t + 0.5, cx, cy),
                      cyl_at(sw['head_diameter'], -0.5, sw['head_depth'], cx, cy)])
    if fc.get('driver_gauge'):
        cx, cy = fc['driver_gauge']['center']
        tools.append(cyl_at(profiles['carrier']['retention']['access_diameter'], -0.5, t + 0.5, cx, cy))
    plate = dif(plate, tools)
    if fc.get('charge_gauge'):
        C = Case(profiles, 'receiver')
        gauge = fc['charge_gauge']
        cx, outer_y = gauge['center_x'], gauge['outer_y']
        width = profiles['charge']['cap_plate'][0] + 4
        wall = box(width, C.wall, C.lid_top() - t, (cx - width / 2, outer_y - C.wall, t))
        _face, mid, _zc, _ow, _oh = C.charge_info()
        shift = (cx - mid, outer_y - C.l, 0)
        port = charge_port_tool(C, C.wall + 0.6)
        seat = charge_seat_tool(C)
        port.apply_translation(shift)
        seat.apply_translation(shift)
        plate = uni(plate, dif(wall, [port, seat]))
    return plate


# ==========================================================================
# 3MF
# ==========================================================================

def write_3mf(path, items):
    colors = []
    for _n, _m, c in items:
        if c not in colors:
            colors.append(c)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<model unit="millimeter" xml:lang="en-US" '
           'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">',
           '<resources>', '<basematerials id="1">']
    for c in colors:
        out.append(f'<base name="color_{c.lstrip("#")}" displaycolor="{c}FF"/>')
    out.append('</basematerials>')
    ids, oid = [], 2
    for name, mesh, color in items:
        mesh = prepare_export(mesh)
        if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume <= 0:
            raise ValueError(f'{name}: invalid mesh for 3MF export')
        v = np.asarray(mesh.vertices, float)
        f = np.asarray(mesh.faces, int)
        pi = colors.index(color)
        out.append(f'<object id="{oid}" type="model" name="{escape(name)}"><mesh><vertices>')
        for p in v:
            # Preserve the small vertex separations used by STL preparation.
            # Four decimal places can merge them and reopen the exported mesh.
            out.append(f'<vertex x="{p[0]:.9f}" y="{p[1]:.9f}" z="{p[2]:.9f}"/>')
        out.append('</vertices><triangles>')
        for t in f:
            out.append(f'<triangle v1="{t[0]}" v2="{t[1]}" v3="{t[2]}" '
                       f'pid="1" p1="{pi}" p2="{pi}" p3="{pi}"/>')
        out.append('</triangles></mesh></object>')
        ids.append(oid)
        oid += 1
    out.append(f'<object id="{oid}" type="model" name="assembly"><components>')
    for i in ids:
        out.append(f'<component objectid="{i}"/>')
    out.append('</components></object></resources>')
    out.append(f'<build><item objectid="{oid}"/></build></model>')
    ct = ('<?xml version="1.0" encoding="UTF-8"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
          '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with retry_io(lambda: zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED)) as z:
        z.writestr('[Content_Types].xml', ct)
        z.writestr('_rels/.rels', rels)
        z.writestr('3D/3dmodel.model', ''.join(out))


# ==========================================================================
# rendering
# ==========================================================================

PREVIEW_BG = (247, 248, 250)


def render_mesh_array(items, width, height, ss=2, bg=PREVIEW_BG, pad=0.92):
    from PIL import Image
    W, H = width * ss, height * ss
    verts, faces, face_col = [], [], []
    off = 0
    for mesh, col in items:
        v = np.asarray(mesh.vertices, float)
        f = np.asarray(mesh.faces, np.int64)
        verts.append(v)
        faces.append(f + off)
        off += len(v)
        face_col.append(np.tile(np.asarray(col, float), (len(f), 1)))
    if not faces:
        return Image.new('RGB', (width, height), bg)
    V = np.vstack(verts)
    F = np.vstack(faces)
    FC = np.vstack(face_col)
    c = (V.min(axis=0) + V.max(axis=0)) / 2.0
    d = np.array([0.42, 0.78, -0.46])
    d /= np.linalg.norm(d)
    right = np.cross(d, [0, 0, 1.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, d)
    rel = V - c
    px, py, pz = rel @ right, rel @ up, rel @ d
    ex, ey = px.max() - px.min(), py.max() - py.min()
    scale = pad * min(W / max(ex, 1e-6), H / max(ey, 1e-6))
    sx = px * scale + W / 2.0
    sy = -py * scale + H / 2.0
    tri = np.stack([np.column_stack([sx[F[:, 0]], sy[F[:, 0]], pz[F[:, 0]]]),
                    np.column_stack([sx[F[:, 1]], sy[F[:, 1]], pz[F[:, 1]]]),
                    np.column_stack([sx[F[:, 2]], sy[F[:, 2]], pz[F[:, 2]]])], axis=1)
    v0, v1, v2 = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    nrm = np.cross(v1 - v0, v2 - v0)
    nrm = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    keep = (nrm @ d) < -1e-6
    tri, nrm, FC = tri[keep], nrm[keep], FC[keep]
    l1 = np.array([0.35, -0.55, 0.75]); l1 /= np.linalg.norm(l1)
    l2 = np.array([-0.6, 0.3, 0.4]); l2 /= np.linalg.norm(l2)
    shade = 0.34 + 0.56 * np.clip(nrm @ l1, 0, 1) + 0.16 * np.clip(nrm @ l2, 0, 1)
    col = np.clip(FC * shade[:, None], 0, 1)
    zbuf = np.full((H, W), np.inf)
    img = np.empty((H, W, 3))
    img[:] = np.asarray(bg, float) / 255.0
    for i in range(len(tri)):
        t = tri[i]
        x0 = max(int(np.floor(t[:, 0].min())), 0)
        x1 = min(int(np.ceil(t[:, 0].max())) + 1, W)
        y0 = max(int(np.floor(t[:, 1].min())), 0)
        y1 = min(int(np.ceil(t[:, 1].max())) + 1, H)
        if x1 <= x0 or y1 <= y0:
            continue
        den = ((t[1, 1] - t[2, 1]) * (t[0, 0] - t[2, 0]) +
               (t[2, 0] - t[1, 0]) * (t[0, 1] - t[2, 1]))
        if abs(den) < 1e-9:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        a = ((t[1, 1] - t[2, 1]) * (xs - t[2, 0]) +
             (t[2, 0] - t[1, 0]) * (ys - t[2, 1])) / den
        b = ((t[2, 1] - t[0, 1]) * (xs - t[2, 0]) +
             (t[0, 0] - t[2, 0]) * (ys - t[2, 1])) / den
        cc = 1.0 - a - b
        inside = (a >= 0) & (b >= 0) & (cc >= 0)
        if not inside.any():
            continue
        z = a * t[0, 2] + b * t[1, 2] + cc * t[2, 2]
        sub_z = zbuf[y0:y1, x0:x1]
        upd = inside & (z < sub_z)
        if not upd.any():
            continue
        sub_z[upd] = z[upd]
        sub_img = img[y0:y1, x0:x1]
        sub_img[upd] = col[i]
        zbuf[y0:y1, x0:x1] = sub_z
    out = (np.clip(img, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(out, 'RGB').resize((width, height), Image.LANCZOS)


def hex_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def text_size(draw, txt, font):
    if font is None:
        return (len(txt) * 6, 10)
    b = draw.textbbox((0, 0), txt, font=font)
    return (b[2] - b[0], b[3] - b[1])


def render_part_sheet(cells, path, cols=4, cell=(360, 300)):
    from PIL import Image, ImageDraw, ImageFont
    try:
        font_s = ImageFont.load_default(size=13)
        font_m = ImageFont.load_default(size=15)
    except Exception:
        font_s = font_m = None
    rows = (len(cells) + cols - 1) // cols
    W, Hc = cell
    img = Image.new('RGB', (cols * W, rows * Hc), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    for i, (label, mesh, color, caption) in enumerate(cells):
        r, c = divmod(i, cols)
        x0, y0 = c * W, r * Hc
        draw.rectangle([x0 + 6, y0 + 6, x0 + W - 6, y0 + Hc - 6], outline=(226, 226, 226))
        try:
            sub = render_mesh_array([(mesh, hex_rgb(color))], W - 30, Hc - 96, ss=2)
            img.paste(sub, (x0 + 15, y0 + 12))
        except Exception:
            pass
        tw, _ = text_size(draw, label, font_m)
        draw.text((x0 + W / 2 - tw / 2, y0 + Hc - 74), label, fill=(25, 25, 25), font=font_m)
        tw, _ = text_size(draw, caption, font_s)
        draw.text((x0 + W / 2 - tw / 2, y0 + Hc - 52), caption, fill=(100, 100, 100), font=font_s)
    retry_io(lambda: img.save(path))
    return len(cells)


# ==========================================================================
# one style: build, export, validate
# ==========================================================================

def build_style(profiles, style, outdir, palette):
    C = Case(profiles, style)
    g = profiles
    p = C.p
    prints, colors = {}, {}

    body = build_body(C)
    notes = []
    body = clean_part(body, C.name('body'), notes)
    lid = build_lid(C)
    lid = clean_part(lid, C.name('lid'), notes)
    deck = build_deck(C)
    cap = build_charge_cap(C)
    cap_asm = xform(cap, charge_cap_matrix(C))
    prints[C.name('body')] = (sit_on_bed(body), body)
    prints[C.name('lid')] = (sit_on_bed(lid), lid)
    prints[C.name('deck')] = (sit_on_bed(deck), deck)
    prints[C.name('charge_cap')] = (sit_on_bed(cap), cap_asm)
    colors[C.name('body')] = palette['cyan']
    colors[C.name('lid')] = palette['pink']
    colors[C.name('deck')] = palette['cyan']
    colors[C.name('charge_cap')] = palette['cyan']

    for m in C.mounts():
        car = build_carrier(C, m)
        stem = C.name(f"{m['name']}_carrier")
        prints[stem] = (sit_on_bed(xform(car, ry(180))), None)
        colors[stem] = palette['cyan']

    for i, b in enumerate(C.buttons(), start=1):
        local, button_head = build_plunger_parts_local(C, b)
        stem = C.name(f"plunger_{b['id']}") if len(C.buttons()) > 1 else C.name(f"plunger_{i}")
        asm = xform(local, C.frame(*C.button_center(b)))
        print_local = local if C.pl.get('joint') else xform(local, rx(180))
        prints[stem] = (sit_on_bed(print_local), asm)
        colors[stem] = palette['white']
        if button_head is not None:
            prints[stem + '_head'] = (sit_on_bed(xform(button_head, rx(180))),
                                      xform(button_head, C.frame(*C.button_center(b))))
            colors[stem + '_head'] = palette['white']
        if str(b.get('head')) == 'numbered':
            lb = build_label_local(C, b)
            lstem = C.name(f"label_{b['id']}")
            prints[lstem] = (sit_on_bed(lb), xform(lb, label_matrix(C, b)))
            colors[lstem] = palette['cyan']

    if p.get('sidebar'):
        sb = p['sidebar']
        sp, button_head = build_side_plunger_parts_local(C)
        asm = xform(sp, side_plunger_matrix(C))
        print_rot = rx(90) if C.pl.get('joint') or sb.get('face', 'y_max') == 'y_min' else rx(-90)
        prints[C.name(f"plunger_{sb['id']}")] = (sit_on_bed(xform(sp, print_rot)), asm)
        colors[C.name(f"plunger_{sb['id']}")] = palette['pink']
        if button_head is not None:
            stem = C.name(f"plunger_{sb['id']}_head")
            prints[stem] = (sit_on_bed(xform(button_head, rx(-90))), xform(button_head, side_plunger_matrix(C)))
            colors[stem] = palette['pink']

    if p.get('bezel'):
        bz = build_bezel_local(C)
        prints[C.name('display_bezel')] = (sit_on_bed(bz), xform(bz, bezel_matrix(C)))
        colors[C.name('display_bezel')] = palette['pink']

    # ---- export ----------------------------------------------------------
    report = {
        "style": style, "role": p['role'],
        "outer_mm": [C.w, C.l, round(C.lid_top(), 2)],
        "flat_case_mm": round(C.lid_top(), 2),
        "dashboard_tilt_deg": float(C.dash['tilt_deg']) if C.dash else None,
        "parts": {}, "reserved_component_spaces": {}, "checks": {},
        "control_deck": {}, "mounts": [],
    }
    failures, warnings = [], []
    max_z = C.lid_top()
    for b in C.buttons():
        cx, cy = C.button_center(b)
        _h, _hd, hh = plunger_head_sizes(C, b)
        well_d = float(C.well_params()['depth'])
        max_z = max(max_z, C.surface_z(cx, cy) - float(C.pl.get('face_recess', well_d - hh)))
    if p.get('oled') and C.dash and C.dash.get('head'):
        h = C.dash['head']
        max_z = max(max_z, C.head_base() + h['length'] * math.tan(math.radians(C.dash['tilt_deg'])))
        max_z = max(max_z, C.head_base() + h['length'] * math.tan(math.radians(C.dash['tilt_deg'])) + g['bezel']['hood_height'])
    if p.get('guard'):
        max_z = max(max_z, C.lid_top() + float(p['guard']['height']))
    report['max_height_mm'] = round(max_z, 2)

    for stem, (pm, _asm) in prints.items():
        out = prepare_export(pm)
        path = os.path.join(outdir, stem + ".stl")
        retry_io(lambda: out.export(path, file_type='stl'))
        disk = retry_io(lambda: trimesh.load(path, force='mesh'))
        rep = mesh_report(disk, stem + ".stl")
        report['parts'][stem] = rep
        if not rep['watertight']:
            failures.append(f"{stem}: not watertight")
        if not rep['winding_consistent']:
            failures.append(f"{stem}: winding inconsistent")
        if rep['components'] != 1:
            failures.append(f"{stem}: {rep['components']} shells")
        if rep['negative_z']:
            failures.append(f"{stem}: below z=0")
        if rep['volume_mm3'] <= 0:
            failures.append(f"{stem}: volume <= 0")

    case_parts = [body, lid]

    def check_shape(name, shape, note=''):
        vol, depth, hits = probe_violation(shape, case_parts)
        entry = {"bounds_mm": [round(x, 3) for x in aabb(shape)],
                 "enclosure_collision_mm3": round(vol, 3),
                 "max_penetration_mm": round(depth, 2),
                 "sample_hits": hits, "hardware_measured": False, "note": note}
        if vol > 40.0 or depth > 0.55:
            failures.append(f"{style}:{name}: reserved space intrudes ~{vol:.1f} mm3 "
                            f"(depth {depth:.1f} mm)")
        elif vol > 2.0:
            warnings.append(f"{style}:{name}: marginal ~{vol:.1f} mm3 (depth {depth:.2f} mm)")
            entry["marginal"] = True
        report['reserved_component_spaces'][name] = entry
        return vol

    # board: flat, components up, USB shell allowance
    bd = g['board']
    bx0, by0, bx1, by1 = C.board_rect()
    zb, zt = C.board_z()
    board_shape = uni(box(bx1 - bx0 - 1.6, by1 - by0 - 1.6,
                          float(bd['pcb_thickness']),
                          (bx0 + 0.8, by0 + 0.8, zb - 0.05)),
                      box(max(bx1 - bx0 - 13.6, 4.0), max(by1 - by0 - 13.6, 4.0),
                          float(bd['component_stack']),
                          (bx0 + 6.8, by0 + 6.8, zt - 0.05)))
    check_shape('xiao_nrf54l15', board_shape)
    hdr = bd.get('header') or {}
    header_shape = fillet_shape = None
    if hdr:
        pins = int(hdr['pins'])
        pitch = float(hdr['pitch'])
        hw, hh = float(hdr['width']), float(hdr['height'])
        fl = float(hdr['fillet'])
        sl = (pins - 1) * pitch + pitch
        strips, fillets = [], []
        if (bx1 - bx0) >= (by1 - by0):
            # 21 mm axis is x: strips run along x on the y_min/y_max edges
            sx0 = (bx0 + bx1 - sl) / 2.0
            for yy in (by0, by1 - hw):
                strips.append(box(sl, hw, hh, (sx0, yy, zt)))
                fillets.append(box(sl, hw, fl, (sx0, yy, zb - fl)))
        else:
            sy0 = (by0 + by1 - sl) / 2.0
            for xx in (bx0, bx1 - hw):
                strips.append(box(hw, sl, hh, (xx, sy0, zt)))
                fillets.append(box(hw, sl, fl, (xx, sy0, zb - fl)))
        header_shape = uni(*strips)
        fillet_shape = uni(*fillets)
        check_shape('xiao_headers', header_shape,
                    note='pre-soldered 1x7 header strips on the 21 mm board edges, component side')
        check_shape('xiao_solder_fillets', fillet_shape,
                    note='solder fillet allowance below the PCB at the trimmed pins, pad side')
    shell = box(9.0, 3.5, float(bd['usb_shell_height']),
                ((bx0 + bx1) / 2.0 - 4.5, 0.0, zt))
    # place shell at the USB end based on the wall
    face = p['charge']['face']
    shell_z = zt + 0.1
    if face == 'y_max':
        shell = box(8.0, 3.5, float(bd['usb_shell_height']), ((bx0 + bx1) / 2.0 - 4.0, C.l - 6.0, shell_z))
    elif face == 'y_min':
        shell = box(8.0, 3.5, float(bd['usb_shell_height']), ((bx0 + bx1) / 2.0 - 4.0, 2.5, shell_z))
    elif face == 'x_max':
        shell = box(3.5, 8.0, float(bd['usb_shell_height']), (C.w - 6.0, (by0 + by1) / 2.0 - 4.0, shell_z))
    else:
        shell = box(3.5, 8.0, float(bd['usb_shell_height']), (2.5, (by0 + by1) / 2.0 - 4.0, shell_z))
    if bd.get('use_manufacturer_usb'):
        import usb_reference
        shell=usb_reference.envelope(SimpleNamespace(**globals()),C)
    check_shape('xiao_usb_shell', shell, note='Board-relative USB courtyard reservation' if bd.get('use_manufacturer_usb') else 'Nominal wall-positioned USB allowance; manufacturer placement not established')
    reserved = {'xiao_nrf54l15': board_shape, 'xiao_usb_shell': shell}
    if header_shape is not None:
        reserved['xiao_headers'] = header_shape
        reserved['xiao_solder_fillets'] = fillet_shape

    # antenna keepout: metal-free band from the deck top to the lid
    kz = C.comp('xiao_antenna_keepout')
    keepout = box(float(kz['width']), float(kz['length']),
                  C.hb - C.deck_z() - 0.2,
                  (float(kz['x']), float(kz['y']), C.deck_z() + 0.2))
    report['reserved_component_spaces']['xiao_antenna_keepout'] = {
        "bounds_mm": [round(v, 3) for v in aabb(keepout)],
        "note": "metal-free band between the deck top and the lid, in front of the board antenna end",
        "hardware_measured": False,
    }
    metal_hits = 0

    if fillet_shape is not None:
        metal_hits += probe_violation(fillet_shape, keepout)[0]

    cell = C.cell()
    cell_shape = rbox(float(cell['width']), float(cell['length']), C.cell_h(),
                      3.5, 1.5, (float(cell['x']), float(cell['y']), C.cell_z()))
    check_shape('protected_cell', cell_shape)
    reserved['protected_cell'] = cell_shape
    metal_hits += probe_violation(cell_shape, keepout)[0]

    if p.get('oled'):
        oled = C.oled_params()
        ox0, oy0, ox1, oy1 = C.oled_rect()
        ccx, ccy = (ox0 + ox1) / 2.0, (oy0 + oy1) / 2.0
        F = C.frame(ccx, ccy)
        sd = float(oled['seat_depth'])
        om = rbox(ox1 - ox0, oy1 - oy0, oled['height'], 1.0, 0.6,
                  (-(ox1 - ox0) / 2.0, -(oy1 - oy0) / 2.0, -sd - oled['height']))
        check_shape('oled_display', xform(om, F))
        reserved['oled_display'] = xform(om, F)
        metal_hits += probe_violation(xform(om, F), keepout)[0]

    for b in C.buttons():
        sc = C.switch_of(b)
        cx, cy = C.button_center(b)
        F = C.frame(cx, cy)
        L = C.local_depth(cx, cy)
        sw_w = float(sc['width'])
        sw_l = float(sc['length'])
        body_h = float(g['switch']['body'][2])
        act_h = float(g['switch']['actuator'][1])
        fl_h = float(C.pl['flange_height'])
        sw_body = rbox(sw_w + 0.2, sw_l + 0.2, body_h + 0.2, 1.2, 1.0,
                       (-(sw_w + 0.2) / 2.0, -(sw_l + 0.2) / 2.0,
                        -L - fl_h - act_h - body_h - 0.2))
        aw = float(g['switch']['actuator'][0]) + 0.6
        sw_act = box(aw, aw, act_h + 0.4, (-aw / 2.0, -aw / 2.0, -L - fl_h - act_h - 0.2))
        sw = uni(sw_body, sw_act)
        check_shape(f"switch_{b['id']}", xform(sw, F))
        reserved[f"switch_{b['id']}"] = xform(sw, F)
        metal_hits += probe_violation(xform(sw, F), keepout)[0]
        asm = xform(build_plunger_local(C, b), F)
        pv, pd, ph = probe_violation(asm, case_parts)
        report['checks'][f"plunger_{b['id']}_collision_mm3"] = round(pv, 3)
        if pv > 40.0 or pd > 0.55:
            failures.append(f"{style}:plunger_{b['id']} intrudes ~{pv:.1f} mm3 (depth {pd:.1f} mm)")
        elif pv > 2.0:
            warnings.append(f"{style}:plunger_{b['id']}: marginal ~{pv:.1f} mm3 (depth {pd:.2f} mm)")

    if p.get('sidebar'):
        sb = p['sidebar']
        sc = C.comp(sb['switch'])
        sw = box(float(sc['width']), float(sc['length']), float(sc['width']),
                 (float(sc['x']), float(sc['y']),
                  float(sb['z']) - float(sc['width']) / 2.0))
        check_shape(f"switch_{sb['id']}", sw)
        reserved[f"switch_{sb['id']}"] = sw
        metal_hits += probe_violation(sw, keepout)[0]
        asm2 = xform(build_side_plunger_local(C), side_plunger_matrix(C))
        pv, pd, ph = probe_violation(asm2, case_parts)
        report['checks'][f"plunger_{sb['id']}_collision_mm3"] = round(pv, 3)
        if pv > 40.0 or pd > 0.55:
            failures.append(f"{style}:plunger_{sb['id']} intrudes ~{pv:.1f} mm3")
        elif pv > 2.0:
            warnings.append(f"{style}:plunger_{sb['id']}: marginal ~{pv:.1f} mm3")

    report['checks']['keepout_metal_mm3'] = round(metal_hits, 3)
    if metal_hits > 1.0:
        failures.append(f"{style}: metal inside the antenna keepout (~{metal_hits:.1f} mm3)")

    # ---- mutual clearances between reserved spaces -------------------------
    rnames = list(reserved.keys())
    skip_pairs = {('xiao_nrf54l15', 'xiao_usb_shell')}
    for i in range(len(rnames)):
        for j in range(i + 1, len(rnames)):
            if (rnames[i], rnames[j]) in skip_pairs:
                continue
            a, b = reserved[rnames[i]], reserved[rnames[j]]
            vol, depth, hits = probe_violation(a, b, pitch=2.5)
            key = f"mutual_{rnames[i]}_vs_{rnames[j]}_mm3"
            report['checks'][key] = round(vol, 2)
            if vol > 40.0 or depth > 0.5:
                failures.append(f"{style}: {rnames[i]} overlaps {rnames[j]} "
                                f"(~{vol:.1f} mm3, depth {depth:.1f} mm)")
            elif vol > 15.0:
                warnings.append(f"{style}: {rnames[i]} vs {rnames[j]} marginal "
                                f"(~{vol:.1f} mm3, depth {depth:.2f} mm)")

    # ---- feature proofs ---------------------------------------------------
    def ray_hits(mesh, origin, direction):
        loc, _, _ = mesh.ray.intersects_location(ray_origins=[origin],
                                                 ray_directions=[direction],
                                                 multiple_hits=True)
        return len(loc)

    face, mid, zc, ow, oh = C.charge_info()
    near = C.wall + 1.2
    if face == 'y_max':
        orig = [mid, C.l - near, zc]
        hits = ray_hits(body, orig, [0, 1, 0]) + ray_hits(lid, orig, [0, 1, 0])
    elif face == 'y_min':
        orig = [mid, near, zc]
        hits = ray_hits(body, orig, [0, -1, 0]) + ray_hits(lid, orig, [0, -1, 0])
    elif face == 'x_max':
        orig = [C.w - near, mid, zc]
        hits = ray_hits(body, orig, [1, 0, 0]) + ray_hits(lid, orig, [1, 0, 0])
    else:
        orig = [near, mid, zc]
        hits = ray_hits(body, orig, [-1, 0, 0]) + ray_hits(lid, orig, [-1, 0, 0])
    report['checks']['usb_opening_ray_hits'] = int(hits)
    if hits != 0:
        failures.append(f"{style}: charge opening blocked ({hits} hits)")

    if p.get('oled'):
        ox0, oy0, ox1, oy1 = C.oled_rect()
        F = C.frame((ox0 + ox1) / 2.0, (oy0 + oy1) / 2.0)
        base = (F @ np.array([0, 0, 60.0, 1.0]))[:3]
        d = F[:3, :3] @ np.array([0, 0, -1.0])
        hits = ray_hits(lid, base, d)
        report['checks']['window_ray_hits'] = int(hits)
        if hits != 0:
            failures.append(f"{style}: OLED window blocked ({hits} hits)")

    for b in C.buttons():
        cx, cy = C.button_center(b)
        F = C.frame(cx, cy)
        base = (F @ np.array([0, 0, 60.0, 1.0]))[:3]
        d = F[:3, :3] @ np.array([0, 0, -1.0])
        hits = ray_hits(lid, base, d)
        report['checks'][f"button_{b['id']}_ray_hits"] = int(hits)
        if hits != 0:
            failures.append(f"{style}: button {b['id']} hole blocked ({hits} hits)")

    pilot_ok = True
    for (sx, sy) in p['fasteners']:
        # lid: the pilot must be blind, with a roof of material under the outer face
        loc, _, _ = lid.ray.intersects_location(ray_origins=[[sx, sy, 300.0]],
                                                ray_directions=[[0, 0, -1]],
                                                multiple_hits=True)
        zs = sorted(float(v) for v in loc[:, 2]) if len(loc) else []
        report['checks'][f"pilot_{sx}_{sy}_z"] = [round(z, 2) for z in zs]
        roof = (zs[-1] - zs[-2]) if len(zs) >= 2 else 0.0
        if roof < 0.8 or zs[-1] < C.lid_top() - 0.05:
            pilot_ok = False
        # body: the floor must give the screw a clear path in from the back
        loc, _, _ = body.ray.intersects_location(ray_origins=[[sx, sy, -300.0]],
                                                 ray_directions=[[0, 0, 1]],
                                                 multiple_hits=True)
        bz = sorted(float(v) for v in loc[:, 2]) if len(loc) else []
        report['checks'][f"screw_{sx}_{sy}_z"] = [round(z, 2) for z in bz]
        if bz:
            pilot_ok = False
        # body: head counterbore land under the socket wall
        ox = sx + (C.screw['clearance'] + C.screw['head_diameter']) / 4.0
        loc, _, _ = body.ray.intersects_location(ray_origins=[[ox, sy, -300.0]],
                                                 ray_directions=[[0, 0, 1]],
                                                 multiple_hits=True)
        hz = sorted(float(v) for v in loc[:, 2]) if len(loc) else []
        report['checks'][f"head_{sx}_{sy}_z"] = [round(z, 2) for z in hz]
        if C.screw.get('seat_reinforcement'):
            thicknesses = []
            # Probe across the bearing annulus, including its outside edge.
            # A single middle ring misses pads clipped too close to a cell bay.
            radii = np.linspace(C.screw['clearance'] / 2 + 0.05,
                                C.screw['head_diameter'] / 2 - 0.05, 3)
            for radius in radii:
                for angle in np.arange(48) * 2 * math.pi / 48:
                    loc, _, _ = body.ray.intersects_location(
                        ray_origins=[[sx + radius * math.cos(angle), sy + radius * math.sin(angle), -300]],
                        ray_directions=[[0, 0, 1]], multiple_hits=True)
                    seat_hits = sorted(float(v) for v in loc[:, 2]) if len(loc) else []
                    thicknesses.append(seat_hits[1] - seat_hits[0] if len(seat_hits) >= 2 else 0)
            minimum = min(thicknesses)
            report['checks'][f"screw_seat_{sx}_{sy}_min_bearing_mm"] = round(minimum, 3)
            if minimum < C.floor + C.screw['seat_reinforcement']['height'] - C.screw['head_depth'] - 0.05:
                failures.append(f'{style}: screw seat {sx},{sy} has inadequate reinforced bearing')
        seat_ok = (len(hz) >= 2 and abs(hz[0] - C.screw['head_depth']) < 0.05
                   and hz[-1] > hz[0] + 0.3)
        if not seat_ok:
            pilot_ok = False
    if not pilot_ok:
        failures.append(f"{style}: pilot not blind or screw seat wrong")

    # lip engagement
    lip_probe = body.copy()
    v, d, h = probe_violation(lid, body, pitch=3.0)
    report['checks']['lid_body_collision_mm3'] = round(v, 3)
    if v > 40.0:
        failures.append(f"{style}: lid collides with body (~{v:.1f} mm3)")

    # ---- control deck / protection ----------------------------------------
    bz = g['bezel']
    tilt = float(C.dash['tilt_deg']) if C.dash else 0.0
    op = C.oled_params() if p.get('oled') else None
    control_deck = {
        "tilt_deg": tilt if C.dash else None,
        "flat_case_height_mm": round(C.lid_top(), 2),
        "max_height_mm": report['max_height_mm'],
        "screen_recess_mm": round(float(op['seat_depth']) + bz['height'], 2) if op else None,
        "bezel_height_mm": bz['height'] if p.get('oled') else None,
        "hood_height_mm": bz['hood_height'] if p.get('oled') else None,
        "plunger_top_vs_surface_mm": {},
        "plunger_axial_clearance_mm": {},
        "nominal_switch_travel_mm": C.sw.get('nominal_travel'),
    }
    well_h = float(C.well_params()['depth'])
    for b in C.buttons():
        cx, cy = C.button_center(b)
        _h, _hd, hh = plunger_head_sizes(C, b)
        recess = float(C.pl.get('face_recess', well_h - hh))
        clearance = well_h - recess - hh
        control_deck['plunger_top_vs_surface_mm'][b['id']] = round(-recess, 2)
        control_deck['plunger_axial_clearance_mm'][b['id']] = round(clearance, 3)
        if C.sw.get('nominal_travel') is not None and clearance + 0.00001 < C.sw['nominal_travel'] + C.pl['travel_clearance']:
            failures.append(f'{style}:{b["id"]} has insufficient button travel clearance')
    if p.get('sidebar'):
        sid = p['sidebar']['id']
        recess = float(C.pl.get('face_recess', 0.2))
        clearance = 1.4 - recess - C.pl['head_back'][1]
        control_deck['plunger_top_vs_surface_mm'][sid] = -recess
        control_deck['plunger_axial_clearance_mm'][sid] = round(clearance, 3)
        if C.sw.get('nominal_travel') is not None and clearance + 0.00001 < C.sw['nominal_travel'] + C.pl['travel_clearance']:
            failures.append(f'{style}:{sid} has insufficient button travel clearance')
    report['control_deck'] = control_deck
    for m in C.mounts():
        report['mounts'].append({"name": m['name'], "strap_width_mm": float(m['strap_width']),
                                 "layout": m.get('layout'), "loop_count": len(m['centers'])})

    wb = g.get('watch_bars')
    if p.get('bars') and wb:
        bd, stand, bite = float(wb['bar']), float(wb['standoff']), float(wb['bite'])
        report['watch_bars'] = {
            "bar_mm": bd,
            "standoff_mm": stand,
            "clear_width_mm": float(wb['clear_width']),
            "arm_width_mm": float(wb['arm_width']),
            "bite_mm": bite,
            "bar_axis_spacing_mm": round(C.l + bd - 2.0 * bite, 2),
            "overall_length_mm": round(C.l + 2.0 * (bd - bite), 2),
            "max_strap_thickness_mm": round(stand - 0.2, 2),
            "strap_width_mm": float(wb['clear_width']),
            "note": wb.get('note', ''),
        }

    report['checks']['failures'] = failures
    report['checks']['warnings'] = warnings
    report['checks']['all_passed'] = (len(failures) == 0)

    # preview items
    items = [(body, hex_rgb(palette['cyan'])), (lid, hex_rgb(palette['pink'])),
             (deck, hex_rgb(palette['cyan'])), (cap_asm, hex_rgb(palette['cyan']))]
    for i, b in enumerate(C.buttons(), start=1):
        stem = C.name(f"plunger_{b['id']}") if len(C.buttons()) > 1 else C.name(f"plunger_{i}")
        items.append((prints[stem][1], hex_rgb(palette['white'])))
        if stem + '_head' in prints:
            items.append((prints[stem + '_head'][1], hex_rgb(palette['white'])))
        if str(b.get('head')) == 'numbered':
            items.append((prints[C.name(f"label_{b['id']}")][1], hex_rgb(palette['cyan'])))
    for m in C.mounts():
        items.append((build_carrier(C, m), hex_rgb(palette['cyan'])))
    if p.get('sidebar'):
        stem = C.name(f"plunger_{p['sidebar']['id']}")
        items.append((prints[stem][1], hex_rgb(palette['pink'])))
        if stem + '_head' in prints:
            items.append((prints[stem + '_head'][1], hex_rgb(palette['pink'])))
    if p.get('bezel'):
        items.append((xform(build_bezel_local(C), bezel_matrix(C)), hex_rgb(palette['pink'])))
    return C, report, prints, colors, items


# ==========================================================================
# main
# ==========================================================================

def main(argv=None):
    ap = argparse.ArgumentParser(description="PitchComm field-case generator")
    ap.add_argument('--only', default=None)
    ap.add_argument('--no-preview', action='store_true')
    args = ap.parse_args(argv)

    with open(PROFILES_PATH, 'r', encoding='utf-8') as fh:
        profiles = json.load(fh)
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    if not args.only:
        stale = (glob.glob(os.path.join(EXPORTS_DIR, '*.stl')) +
                 glob.glob(os.path.join(EXPORTS_DIR, '*.3mf')) +
                 glob.glob(os.path.join(EXPORTS_DIR, '*.svg')))
        for path in stale:
            try:
                os.remove(path)
            except OSError:
                pass
        legacy = os.path.join(EXPORTS_DIR, "dimensions.json")
        if os.path.exists(legacy):
            try:
                os.remove(legacy)
            except OSError:
                pass
    styles = [args.only] if args.only else ['receiver', 'wrist', 'keypad']
    palette = profiles['palette']

    t0 = time.time()
    dims = {"revision": profiles['revision'], "units": "mm",
            "generator": ".tools/cad-source/generate_cases.py",
            "engine": ENGINE, "trimesh_version": trimesh.__version__,
            "hardware_measured": False,
            "parts": {}, "styles": {}, "fit_coupon": {}, "previews": {}, "validation": {}}
    failures, sheet, scene_units = [], [], []

    for style in styles:
        C, report, prints, colors, items = build_style(profiles, style, EXPORTS_DIR, palette)
        dims['styles'][style] = report
        for stem, rep in report['parts'].items():
            dims['parts'][stem] = rep
        for stem, (pm, _asm) in prints.items():
            retry_io(lambda: prepare_export(pm).export(
                os.path.join(EXPORTS_DIR, stem + "_color.stl"), file_type='stl'))
        write_3mf(os.path.join(EXPORTS_DIR, f"{style}_colored.3mf"),
                  [(stem, asm if asm is not None else pm, colors[stem])
                   for stem, (pm, asm) in prints.items()])
        lid_group = [s for s in prints if ('lid' in s or 'bezel' in s or 'label' in s)]
        write_3mf(os.path.join(EXPORTS_DIR, f"{style}_lid_colored.3mf"),
                  [(s, prints[s][0], colors[s]) for s in lid_group])
        for stem, (pm, _asm) in prints.items():
            cap = f"{inches(pm.extents[0])} x {inches(pm.extents[1])} x {inches(pm.extents[2])} in"
            sheet.append((stem, pm, colors[stem], cap))
        C.max_h = report['max_height_mm']
        scene_units.append((C, items, prints))
        fl = report['checks']['failures']
        failures.extend(fl)
        print(f"[{style}] {C.w:g} x {C.l:g} mm, flat {C.lid_top():.1f} mm, "
              f"max {report['max_height_mm']:.1f} mm, tilt "
              f"{report['dashboard_tilt_deg']}, {len(prints)} parts, failures: {len(fl)}")
        for f in fl:
            print("    !!", f)

    coupon = build_fit_coupon(profiles)
    coupon = prepare_export(coupon)
    retry_io(lambda: coupon.export(os.path.join(EXPORTS_DIR, "fit_coupon.stl"),
                                   file_type='stl'))
    rep = mesh_report(coupon, "fit_coupon.stl")
    dims['fit_coupon'] = rep
    for key in ('watertight', 'winding_consistent', 'on_bed'):
        if not rep[key]:
            failures.append(f'fit_coupon: {key} failed')
    if rep['components'] != 1 or rep['negative_z'] or rep['volume_mm3'] <= 0:
        failures.append('fit_coupon: invalid shell, bed placement or volume')
    sheet.append(("fit_coupon", coupon, palette['cyan'],
                  ' x '.join(inches(v) for v in rep['size_mm']) + ' in'))

    pal = {"revision": profiles['revision'],
           "colors": {k: palette[k] for k in ('cyan', 'pink', 'white')},
           "stl_color_support": False, "assemblies": {}}
    for style in styles:
        parts = []
        for stem, r in dims['styles'][style]['parts'].items():
            parts.append({"file": stem + "_color.stl",
                          "color": (palette['pink'] if ('lid' in stem or 'bezel' in stem or 'plunger_back' in stem)
                                    else palette['white'] if 'plunger' in stem and 'back' not in stem
                                    else palette['cyan']),
                          "bounds_mm": r['bounds_mm'], "components": r['components']})
        pal['assemblies'][style] = {"file": f"{style}_colored.3mf",
                                    "lid_print_file": f"{style}_lid_colored.3mf",
                                    "parts": parts, "stl_color_support": False}
    def write_json(path, obj):
        def go():
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(obj, fh, indent=2)
        retry_io(go)

    write_json(os.path.join(EXPORTS_DIR, "palette.json"), pal)

    validated_parts = list(dims['parts'].values()) + [dims['fit_coupon']]
    dims['validation'] = {
        "all_parts_watertight": all(v['watertight'] for v in validated_parts),
        "all_parts_on_bed": all(v['on_bed'] for v in validated_parts),
        "all_parts_single_shell": all(v['components'] == 1 for v in validated_parts),
        "all_volumes_positive": all(v['volume_mm3'] > 0 for v in validated_parts),
        "failures": failures,
        "checks_passed": len(failures) == 0,
    }

    if not args.no_preview:
        tp = time.time()
        gap = 26.0
        off = 0.0
        scene = []
        for C, items, _p in scene_units:
            for mesh, col in items:
                m = mesh.copy()
                m.apply_translation((off, 0.0, 0.0))
                scene.append((m, col))
            off += C.w + gap
        retry_io(lambda: render_mesh_array(scene, 1560, 700, ss=2).save(
            os.path.join(PREVIEW_DIR, "preview.png")))
        render_part_sheet(sheet, os.path.join(PREVIEW_DIR, "parts-preview.png"), cols=4)
        mount_cells = []
        for C, _items, prints_ in scene_units:
            for m in C.mounts():
                stem = C.name(f"{m['name']}_carrier")
                pm = prints_[stem][0]
                mount_cells.append((stem, pm, palette['cyan'],
                                    f"{inches(pm.extents[0])} x {inches(pm.extents[1])} x "
                                    f"{inches(pm.extents[2])} in, {m['strap_width']:g} mm strap"))
                mount_cells.append((stem + ' / case side', build_carrier(C, m), palette['cyan'],
                                    'Lightening windows; continuous rails and screw landings'))
        render_part_sheet(mount_cells, os.path.join(PREVIEW_DIR, "mounts-preview.png"), cols=2)
        dims['previews'] = {
            "method": "built-in software z-buffer renderer (numpy) + Pillow labels; "
                      "trimesh scene.save_image needs pyglet, which is not installed",
            "files": ["preview.png", "parts-preview.png", "mounts-preview.png"],
            "render_seconds": round(time.time() - tp, 2)}
        print(f"[preview] sheets written in {time.time() - tp:.1f}s")

    write_json(DIMS_PATH, dims)
    print(f"wrote {DIMS_PATH} in {time.time() - t0:.1f}s")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print("all checks passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())

