#!/usr/bin/env python3
"""
PitchComm field-case generator.

Builds the three field pods from profiles.json with trimesh + manifold3d CSG.
The shell is a thin flat V1-family tray (tapered skirt, wide rim, inset-lip
lid, hanging screw bosses, internal deck between cell and board, friction
charge cap, two-loop strap carriers).  The controls live on a raised control
deck on the lid: a sloped display head plus, where used, a flat button
plateau.  Only the control deck is tilted.

Part set per style:
    <style>_body.stl, _lid.stl, _deck.stl, _charge_cap.stl,
    <style>_<mount>_carrier.stl, _plunger_*.stl, _label_*.stl,
    _display_bezel.stl, _window.stl
    plus *_color.stl copies, <style>_colored.3mf, <style>_lid_colored.3mf,
    palette.json, fit_coupon.stl, dimensions.json and preview sheets.

Usage:
    python cad/unbranded/generate_cases.py [--only receiver|wrist|keypad]
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
import zipfile
from xml.sax.saxutils import escape

import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORTS_DIR = os.path.join(HERE, "exports")
PROFILES_PATH = os.path.join(HERE, "profiles.json")
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
        self.pl = profiles['plunger']

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
        z0 = self.deck_z() + self.g['deck']['thickness'] + float(self.g['board']['standoff'])
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


# ==========================================================================
# body
# ==========================================================================

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

    # hanging bosses (chamfered base) clear of the cell and the switch holders
    rb = C.screw['boss_diameter'] / 2.0
    deck_r = (C.wall - 0.1, C.deck_span()[0], C.w - C.wall + 0.1, C.deck_span()[1])
    holder_r = C.sw['collar_interior'] / 2.0 + C.sw['collar_wall'] + 0.6
    for (sx, sy) in C.p['fasteners']:
        b1 = C.hb - C.screw['top_gap']
        over_deck = (sx + rb > deck_r[0] and sx - rb < deck_r[2] and
                     sy + rb > deck_r[1] and sy - rb < deck_r[3])
        near_holder = False
        for b in C.buttons():
            cx, cy = C.button_center(b)
            if math.hypot(sx - cx, sy - cy) < rb + holder_r + 1.0:
                near_holder = True
        b0 = C.deck_z() + 0.3 if over_deck else C.floor + 0.2
        if near_holder:
            b0 = max(b0, C.hb - 7.0)
        if b1 - b0 < 4.0:
            b0 = max(C.floor + 0.2, b1 - 4.0)
        height = b1 - b0
        pilot_depth = max(2.2, min(C.screw['pilot_depth'], height - 1.0))
        body = uni(body, cyl_at(C.screw['boss_diameter'], b0 + 1.2, b1, sx, sy))
        cham_h = min(1.2, max(0.3, height - 1.2))
        body = uni(body, cyl((rb + 0.5) * 2.0, cham_h, 'z', (sx, sy, b0 + cham_h / 2.0)))
        body = dif(body, cyl_at(C.screw['pilot'], b1 - pilot_depth, b1 + 1.0, sx, sy))

    # deck ledges (narrow enough to clear the cell), cell bay rails
    d = g['deck']
    dy0, dy1 = C.deck_span()
    ledge = d['ledge_width']
    cx0, cy0, cx1, cy1 = C.cell_rect()
    margin = min(cx0 - C.wall, C.w - C.wall - cx1) - 0.1
    ledge = max(0.5, min(ledge, margin))
    top = C.deck_z() + 0.01
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
    face, mid, zc, ow, oh = C.charge_info()
    if face == 'y_max':
        tool = prism_axis(rr_poly(ow, oh, 1.4), 'y', C.l - wall - 0.6, C.l + 0.6,
                          offset=(mid - ow / 2.0, 0.0, zc - oh / 2.0))
    elif face == 'y_min':
        tool = prism_axis(rr_poly(ow, oh, 1.4), 'y', -0.6, wall + 0.6,
                          offset=(mid - ow / 2.0, 0.0, zc - oh / 2.0))
    elif face == 'x_max':
        tool = prism_axis(rr_poly(ow, oh, 1.4), 'x', C.w - wall - 0.6, C.w + 0.6,
                          offset=(0.0, mid - ow / 2.0, zc - oh / 2.0))
    else:
        tool = prism_axis(rr_poly(ow, oh, 1.4), 'x', -0.6, wall + 0.6,
                          offset=(0.0, mid - ow / 2.0, zc - oh / 2.0))
    body = dif(body, tool)
    cw, chh, ct = cg['cap_plate']
    if face in ('y_max', 'y_min'):
        ya = C.l - cg['seat_depth'] - 0.1 if face == 'y_max' else -0.1
        seat = box(cw + 0.6, cg['seat_depth'] + 0.2, chh + 0.6,
                   (mid - cw / 2.0 - 0.3, ya, zc - chh / 2.0 - 0.3))
    else:
        xa = C.w - cg['seat_depth'] - 0.1 if face == 'x_max' else -0.1
        seat = box(cg['seat_depth'] + 0.2, cw + 0.6, chh + 0.6,
                   (xa, mid - cw / 2.0 - 0.3, zc - chh / 2.0 - 0.3))
    body = dif(body, seat)

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

    # control deck
    plateau, head = dashboard_meshes(C)
    lid = uni(lid, plateau, head)

    # screw clearance holes + counterbores
    for (sx, sy) in C.p['fasteners']:
        lid = dif(lid, cyl_at(C.screw['clearance'], C.hb - 1.0, C.lid_top() + 0.5, sx, sy))
        lid = dif(lid, cyl_at(C.screw['head_diameter'],
                              C.lid_top() - C.screw['head_depth'], C.lid_top() + 0.5,
                              sx, sy))

    # OLED window + seat in the sloped head
    if C.p.get('oled'):
        oled = g['oled']
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
        well_d, well_h = g['well']['diameter'], g['well']['depth']
        well = cyl(well_d, well_h + 2.0, 'z', (0, 0, (2.0 - well_h) / 2.0))
        lid = dif(lid, xform(well, F))
        # plunger hole from the well floor down to the lid inner face
        hole_h = L - well_h
        hole = cyl(C.pl['lid_hole'], hole_h + 0.4, 'z',
                   (0, 0, -(well_h + L) / 2.0))
        lid = dif(lid, xform(hole, F))
        ci = float(C.sw['collar_interior'])
        cw = float(C.sw['collar_wall'])
        cdep = (float(C.sw['body'][2]) + float(C.sw['actuator'][1]) +
                float(C.pl['flange_height']))
        frame = dif(rbox(ci + 2 * cw, ci + 2 * cw, cdep + 0.25, 1.6, 0.5,
                         (-(ci + 2 * cw) / 2.0, -(ci + 2 * cw) / 2.0, -L - cdep - 0.15)),
                    rbox(ci, ci, cdep + 0.65, 1.0, 0.4,
                         (-ci / 2.0, -ci / 2.0, -L - cdep - 0.5)))
        lid = uni(lid, xform(frame, F))

    # board pads on the inner face
    bx0, by0, bx1, by1 = C.board_rect()
    so = float(g['board']['standoff'])
    pads = []
    for px in (bx0 + 2.2, bx1 - 2.2):
        for py in (by0 + 2.2, by1 - 2.2):
            qx, qy = px, py
            for (sx, sy) in C.p['fasteners']:
                d = math.hypot(qx - sx, qy - sy)
                if d < 6.5:
                    push = 6.5 - d + 0.5
                    if abs(qx - sx) >= abs(qy - sy):
                        qx += math.copysign(push, qx - sx)
                    else:
                        qy += math.copysign(push, qy - sy)
            qx = min(max(qx, bx0 + 1.8), bx1 - 1.8)
            qy = min(max(qy, by0 + 1.8), by1 - 1.8)
            pads.append((qx, qy))
    for (qx, qy) in pads:
        lid = uni(lid, cyl_at(4.4, C.board_z()[1], C.hb + 0.1, qx, qy))

    # hood bar along the high edge of the head
    if C.p.get('oled') and C.dash and C.dash.get('head'):
        bz = g['bezel']
        h = C.dash['head']
        ytop = h['y'] + h['length'] - bz['hood'] / 2.0
        F = C.frame(h['x'] + h['width'] / 2.0, ytop)
        hood = box(h['width'] - 10.0, bz['hood'], bz['hood_height'] + 0.15,
                   (-(h['width'] - 10.0) / 2.0, -bz['hood'] / 2.0, -0.1))
        lid = uni(lid, xform(hood, F))

    # charge slot notch through the lid edge (the slot spans the seam)
    cg = g['charge']
    face, mid, zc, ow, oh = C.charge_info()
    wall = C.wall
    deep = wall + 2.6
    if face == 'y_max':
        tool = prism_axis(rr_poly(ow, oh + 4.0, 1.4), 'y', C.l - deep, C.l + 0.6,
                          offset=(mid - ow / 2.0, 0.0, zc - (oh + 4.0) / 2.0))
    elif face == 'y_min':
        tool = prism_axis(rr_poly(ow, oh + 4.0, 1.4), 'y', -0.6, deep,
                          offset=(mid - ow / 2.0, 0.0, zc - (oh + 4.0) / 2.0))
    elif face == 'x_max':
        tool = prism_axis(rr_poly(ow, oh + 4.0, 1.4), 'x', C.w - deep, C.w + 0.6,
                          offset=(0.0, mid - ow / 2.0, zc - (oh + 4.0) / 2.0))
    else:
        tool = prism_axis(rr_poly(ow, oh + 4.0, 1.4), 'x', -0.6, deep,
                          offset=(0.0, mid - ow / 2.0, zc - (oh + 4.0) / 2.0))
    if zc + oh / 2.0 > C.hb - 0.2:
        z_lo = C.hb - 0.6
        z_hi = min(zc + oh / 2.0 + 0.4, C.lid_top() - 0.6)
        nh = max(z_hi - z_lo, 0.4)
        if face == 'y_max':
            tool = prism_axis(rr_poly(ow, nh, 1.4), 'y', C.l - deep, C.l + 0.6,
                              offset=(mid - ow / 2.0, 0.0, z_lo))
        elif face == 'y_min':
            tool = prism_axis(rr_poly(ow, nh, 1.4), 'y', -0.6, deep,
                              offset=(mid - ow / 2.0, 0.0, z_lo))
        elif face == 'x_max':
            tool = prism_axis(rr_poly(ow, nh, 1.4), 'x', C.w - deep, C.w + 0.6,
                              offset=(0.0, mid - ow / 2.0, z_lo))
        else:
            tool = prism_axis(rr_poly(ow, nh, 1.4), 'x', -0.6, deep,
                              offset=(0.0, mid - ow / 2.0, z_lo))
        lid = dif(lid, tool)

    # pocket over the USB shell on the inner face (only if the shell pokes past)
    face_ch = C.p['charge']['face']
    poke = (C.board_z()[1] + float(g['board']['usb_shell_height']) + 0.15) - C.hb
    pocket_d = min(max(poke + 0.25, 0.0), C.lid_t - 0.6)
    if (C.board_z()[1] + float(g['board']['usb_shell_height']) + 0.1) > (C.hb - g['lip']['height']):
        sh_h = pocket_d + 1.75
        if face_ch == 'y_max':
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
    x0, x1 = C.wall - 0.1, C.w - C.wall + 0.1
    z0 = C.deck_z()
    plate = rbox(x1 - x0, dy1 - dy0, t, C.r_in, 0.4, (x0, dy0, z0))
    tools = []
    for (sx, sy) in C.p['fasteners']:
        tools.append(cyl(7.2, t + 6.0, 'z', (sx, sy, z0 - 3.0)))
    pn = d['pull_notch']
    cyc = (C.cell_rect()[1] + C.cell_rect()[3]) / 2.0
    tools.append(box(pn[0], pn[1], t + 6.0, (x1 - pn[0], cyc - pn[1] / 2.0, z0 - 3.0)))
    cg = C.g['charge']
    face, mid, zc, ow, oh = C.charge_info()
    if face in ('y_max', 'y_min'):
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
        tools.append(box(16.0, 14.0, t + 6.0,
                         (float(C.p['sidebar']['x']) - 8.0,
                          C.l - C.wall - 8.0, z0 - 3.0)))
    return dif(plate, tools)


def build_charge_cap(C: Case):
    cg = C.g['charge']
    cw, chh, ct = cg['cap_plate']
    ow, oh = cg['opening']
    pd, pw = cg['plug_depth'], cg['plug_wall']
    plate = rbox(cw, chh, ct, 2.0, 0.6, (-cw / 2.0, -chh / 2.0, 0.0))
    ow2, oh2 = ow + 0.6, oh + 0.6
    outer = rbox(ow2, oh2, pd, 1.2, 0.4, (-ow2 / 2.0, -oh2 / 2.0, ct - 0.1))
    inner = box(ow2 - 2 * pw + 0.02, oh2 - 2 * pw + 0.02, pd + 1.0,
                (-ow2 / 2.0 + pw, -oh2 / 2.0 + pw, ct - 0.6))
    return uni(plate, dif(outer, inner))


def charge_cap_matrix(C: Case):
    """Print frame (plate on the bed, plug up) -> assembled in the side wall."""
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
        ly0 = float(cy) - (strap + 2 * pad) / 2.0
        ly1 = float(cy) + (strap + 2 * pad) / 2.0
        outer = rbox(lx1 - lx0, ly1 - ly0, loop_h, 2.0, 0.5,
                     (lx0, ly0, -plate_t - loop_h + 0.1))
        inner = box(lx1 - lx0 + 2.0, ly1 - ly0 - 2 * wall, loop_h - 1.2,
                    (lx0 - 1.0, ly0 + wall, -plate_t - loop_h + 1.3))
        carrier = uni(carrier, dif(outer, inner))
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


def build_plunger_local(C, b):
    """Control-surface-local frame: +z outward, cap face recessed 0.3."""
    head, hd, hh = plunger_head_sizes(C, b)
    pl = C.pl
    cx, cy = C.button_center(b)
    L = C.local_depth(cx, cy)
    well_d = float(C.g['well']['depth'])
    z_top = -(well_d - hh)      # head bottom sits on the well floor
    z_head_bot = z_top - hh
    fl_top = -L
    fl_bot = fl_top - pl['flange_height']
    shaft = uni(cyl(pl['shaft'], (z_head_bot - fl_bot) + 0.4, 'z',
                    (0, 0, (z_head_bot + fl_bot) / 2.0)),
                cyl(pl['flange'], pl['flange_height'], 'z',
                    (0, 0, (fl_top + fl_bot) / 2.0)))
    m = uni(cyl(hd, hh, 'z', (0, 0, z_top - hh / 2.0)), shaft)
    if head == 'numbered':
        dg = pl['digit']
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


def build_label_local(C, b):
    dg = C.pl['digit']
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


def build_bezel_local(C):
    g = C.g
    bz, oled = g['bezel'], g['oled']
    bw, bl = oled['window']
    ri = (bw + 1.6, bl + 1.6)
    ro = (ri[0] + 2 * bz['frame'], ri[1] + 2 * bz['frame'])
    outer = rbox(ro[0], ro[1], bz['height'], 2.0, 0.6, (-ro[0] / 2.0, -ro[1] / 2.0, 0.0))
    inner = rbox(ri[0], ri[1], bz['height'] + 1.0, 1.4, 0.4,
                 (-ri[0] / 2.0, -ri[1] / 2.0, -0.4))
    return dif(outer, inner)


def build_window_local(C):
    g = C.g
    bw, bl = g['oled']['window']
    w, l = bw + 1.3, bl + 1.3
    return rbox(w, l, g['bezel']['window_thickness'], 1.2, 0.4,
                (-w / 2.0, -l / 2.0, -0.05))


def bezel_matrix(C):
    ox0, oy0, ox1, oy1 = C.oled_rect()
    return C.frame((ox0 + ox1) / 2.0, (oy0 + oy1) / 2.0)


def build_side_plunger_local(C):
    pl = C.pl
    sb = C.p.get('sidebar') or {}
    head = str(sb.get('head', 'back'))
    hd, hh = (pl['head_back'] if head == 'back' else
              pl['head_numbered'] if head == 'numbered' else pl['head_plain'])
    fd, fh = pl['flange'], pl['flange_height']
    L = C.l
    y_head_out = L - 0.2
    y_head_in = y_head_out - hh
    y_fl_top = L - C.wall - 0.0
    y_fl_bot = y_fl_top - fh
    shaft = uni(cyl(pl['shaft'], (y_head_in - y_fl_bot) + 0.4, 'y',
                    (0, (y_head_in + y_fl_bot) / 2.0, 0)),
                cyl(fd, fh, 'y', (0, (y_fl_top + y_fl_bot) / 2.0, 0)))
    return uni(cyl(hd, hh, 'y', (0, y_head_out - hh / 2.0, 0)), shaft)


def side_plunger_matrix(C):
    sb = C.p['sidebar']
    M = np.eye(4)
    M[0, 3] = float(sb['x'])
    M[2, 3] = float(sb['z'])
    if sb.get('face', 'y_max') == 'y_min':
        T = np.eye(4)
        T[1, 3] = C.l
        return T @ rx(180) @ M
    return M


def build_fit_coupon(profiles):
    fc = profiles['fit_coupon']
    w, l, t = fc['size']
    plate = rbox(w, l, t, 3.0, 0.6)
    tools = []
    for d, (cx, cy) in zip(fc['holes'], fc['hole_centers']):
        tools.append(cyl(d, t + 2.0, 'z', (cx, cy, t / 2.0)))
    for s, (cx, cy) in zip(fc['slots'], fc['slot_centers']):
        th = fc['slot_thickness']
        tools.append(prism_axis(rr_poly(s, th, th / 2.0), 'z', -0.5, t + 0.5,
                                offset=(cx - s / 2.0, cy - th / 2.0, 0.0)))
    return dif(plate, tools)


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
        v = np.asarray(mesh.vertices, float)
        f = np.asarray(mesh.faces, int)
        pi = colors.index(color)
        out.append(f'<object id="{oid}" type="model" name="{escape(name)}"><mesh><vertices>')
        for p in v:
            out.append(f'<vertex x="{p[0]:.4f}" y="{p[1]:.4f}" z="{p[2]:.4f}"/>')
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
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
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
    img.save(path)
    return len(cells)


def render_ergonomics(cases, path, width=1560, height=820):
    from PIL import Image, ImageDraw, ImageFont
    try:
        f1 = ImageFont.load_default(size=16)
        f2 = ImageFont.load_default(size=13)
    except Exception:
        f1 = f2 = None
    img = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    n = len(cases)
    panel = width // n
    for i, C in enumerate(cases):
        ox = i * panel
        base = height * 0.74
        s = (panel - 120.0) / max(C.l + 30.0, 120.0)
        x0 = ox + 60.0
        lt = C.lid_top()
        # flat tray outline
        draw.line([(x0, base), (x0, base - lt * s)], fill=(35, 35, 35), width=4)
        draw.line([(x0, base - lt * s), (x0 + C.l * s, base - lt * s)], fill=(35, 35, 35), width=4)
        draw.line([(x0, base), (x0 + C.l * s, base)], fill=(35, 35, 35), width=4)
        draw.line([(x0 + C.l * s, base), (x0 + C.l * s, base - lt * s)], fill=(35, 35, 35), width=4)
        # control deck
        if C.dash and C.dash.get('plateau'):
            q = C.dash['plateau']
            h = q['height']
            draw.line([(x0 + q['y'] * s, base - lt * s),
                       (x0 + q['y'] * s, base - (lt + h) * s)], fill=(35, 35, 35), width=3)
            draw.line([(x0 + q['y'] * s, base - (lt + h) * s),
                       (x0 + (q['y'] + q['length']) * s, base - (lt + h) * s)],
                      fill=(35, 35, 35), width=3)
        if C.dash and C.dash.get('head'):
            h = C.dash['head']
            hb = C.head_base()
            rise = h['length'] * math.tan(math.radians(C.dash['tilt_deg']))
            draw.line([(x0 + h['y'] * s, base - hb * s),
                       (x0 + (h['y'] + h['length']) * s, base - (hb + rise) * s)],
                      fill=(35, 35, 35), width=3)
            draw.line([(x0 + (h['y'] + h['length']) * s, base - hb * s),
                       (x0 + (h['y'] + h['length']) * s, base - (hb + rise) * s)],
                      fill=(35, 35, 35), width=3)
            ym = h['y'] + h['length'] / 2.0
            zm = C.surface_z(h['x'] + h['width'] / 2.0, ym)
            nm = np.array([-math.sin(math.radians(C.dash['tilt_deg'])),
                           math.cos(math.radians(C.dash['tilt_deg']))])
            px, pz = x0 + ym * s, base - zm * s
            draw.line([(px, pz), (px + nm[0] * 90, pz - nm[1] * 90)], fill=(210, 40, 40), width=3)
            draw.text((px + nm[0] * 90 - 20, pz - nm[1] * 90 - 18), "display normal",
                      fill=(210, 40, 40), font=f2)
        # eye line
        er = C.p.get('ergonomics', {})
        eu = er.get('eye_above_pod_mm', 450.0)
        eo = er.get('eye_outboard_mm', 400.0)
        norm = math.hypot(eo, eu)
        ux, uz = eo / norm, -eu / norm
        px, pz = x0 + C.l * 0.55 * s, base - lt * s
        eye = (px + ux * 120.0, pz + uz * 120.0)
        draw.line([(px, pz), eye], fill=(30, 90, 200), width=2)
        draw.ellipse([eye[0] - 6, eye[1] - 6, eye[0] + 6, eye[1] + 6],
                     outline=(30, 90, 200), width=3)
        draw.text((eye[0] + 10, eye[1] - 18), "assumed eye line", fill=(30, 90, 200), font=f2)
        ang = math.degrees(math.atan2(eu, eo))
        tilt = float(C.dash['tilt_deg']) if C.dash else 0.0
        draw.text((ox + 20, 24), f"{C.style} ({C.p['role']})", fill=(20, 20, 20), font=f1)
        draw.text((ox + 20, 46), f"footprint {C.w:.0f} x {C.l:.1f} mm | flat case "
                                 f"{lt:.1f} mm | max height {getattr(C, 'max_h', lt):.1f} mm",
                  fill=(70, 70, 70), font=f2)
        draw.text((ox + 20, 64), f"display head tilt {tilt:.0f} deg | eye line {ang:.0f} deg "
                                 f"above horizontal | offset {abs(ang - (90 - tilt)):.0f} deg",
                  fill=(70, 70, 70), font=f2)
        note = C.p.get('sight_line_note', '')
        for k in range(0, len(note), 78):
            draw.text((ox + 20, 86 + 16 * (k // 78)), note[k:k + 78], fill=(110, 110, 110), font=f2)
    img.save(path)
    return path


def write_svg(C, path):
    s, pad = 4.0, 16
    W, Hh = int(C.w * s + 2 * pad), int(C.l * s + 2 * pad)
    els = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{Hh}">',
           f'<rect width="{W}" height="{Hh}" fill="#ffffff"/>',
           f'<rect x="{pad}" y="{pad}" width="{C.w * s:.1f}" height="{C.l * s:.1f}" '
           f'rx="{C.r_out * s:.1f}" fill="#edf2f7" stroke="#1a202c"/>']

    def rect(x, y, w, l, fill, op=0.75, label=None, dash=None):
        xs, ys = pad + x * s, pad + (C.l - y - l) * s
        d = f' stroke-dasharray="{dash}"' if dash else ''
        out = (f'<rect x="{xs:.1f}" y="{ys:.1f}" width="{w * s:.1f}" height="{l * s:.1f}" '
               f'rx="2" fill="{fill}" fill-opacity="{op}" stroke="#1a202c"{d}/>')
        if label:
            out += (f'<text x="{xs + w * s / 2:.1f}" y="{ys + l * s / 2:.1f}" font-size="10" '
                    f'text-anchor="middle" fill="#1a202c" font-family="monospace">{label}</text>')
        return out

    for c in C.p['components']:
        nm = c['name']
        fill = ('#38a169' if nm.startswith('switch_') else
                '#d69e2e' if 'cell' in nm else
                '#805ad5' if 'oled' in nm else
                '#f6ad55' if 'keepout' in nm else '#2b6cb0')
        dash = '5,3' if 'keepout' in nm else None
        els.append(rect(float(c['x']), float(c['y']), float(c['width']), float(c['length']),
                        fill, 0.4 if dash else 0.75, nm[:14], dash))
    for (sx, sy) in C.p['fasteners']:
        els.append(f'<circle cx="{pad + sx * s:.1f}" cy="{pad + (C.l - sy) * s:.1f}" '
                   f'r="{3.3 * s:.1f}" fill="none" stroke="#1a202c"/>')
    for b in C.buttons():
        cx, cy = C.button_center(b)
        els.append(f'<circle cx="{pad + cx * s:.1f}" cy="{pad + (C.l - cy) * s:.1f}" '
                   f'r="9*s" fill="none" stroke="#e53e3e"/>')
    if C.dash:
        for key, color in (('plateau', '#e53e3e'), ('head', '#805ad5')):
            q = C.dash.get(key)
            if q:
                els.append(rect(q['x'], q['y'], q['width'], q['length'], '#ffffff',
                                1.0, key, '4,2'))
    els.append(f'<text x="10" y="{Hh - 4}" font-size="11" font-family="monospace">'
               f'{C.style} ({C.p["role"]}) {C.w:g} x {C.l:g} mm, flat lid '
               f'{C.lid_top():.1f} mm</text>')
    els.append('</svg>')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(els))


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
        local = build_plunger_local(C, b)
        stem = C.name(f"plunger_{b['id']}") if len(C.buttons()) > 1 else C.name(f"plunger_{i}")
        asm = xform(local, C.frame(*C.button_center(b)))
        prints[stem] = (sit_on_bed(xform(local, rx(180))), asm)
        colors[stem] = palette['white']
        if str(b.get('head')) == 'numbered':
            lb = build_label_local(C, b)
            lstem = C.name(f"label_{b['id']}")
            prints[lstem] = (sit_on_bed(lb), xform(lb, C.frame(*C.button_center(b))))
            colors[lstem] = palette['cyan']

    if p.get('sidebar'):
        sb = p['sidebar']
        sp = build_side_plunger_local(C)
        asm = xform(sp, side_plunger_matrix(C))
        print_rot = rx(90) if sb.get('face', 'y_max') == 'y_min' else rx(-90)
        prints[C.name(f"plunger_{sb['id']}")] = (sit_on_bed(xform(sp, print_rot)), asm)
        colors[C.name(f"plunger_{sb['id']}")] = palette['pink']

    if p.get('bezel'):
        bz = build_bezel_local(C)
        prints[C.name('display_bezel')] = (sit_on_bed(bz), xform(bz, bezel_matrix(C)))
        colors[C.name('display_bezel')] = palette['pink']
        wn = build_window_local(C)
        prints[C.name('window')] = (sit_on_bed(wn), xform(wn, bezel_matrix(C)))
        colors[C.name('window')] = palette['pink']

    # ---- export ----------------------------------------------------------
    report = {
        "style": style, "role": p['role'],
        "outer_mm": [C.w, C.l, round(C.lid_top(), 2)],
        "flat_case_mm": round(C.lid_top(), 2),
        "dashboard_tilt_deg": float(C.dash['tilt_deg']) if C.dash else None,
        "parts": {}, "reserved_component_spaces": {}, "checks": {},
        "ergonomics": {}, "mounts": [],
    }
    failures, warnings = [], []
    max_z = C.lid_top()
    for b in C.buttons():
        cx, cy = C.button_center(b)
        _h, _hd, hh = plunger_head_sizes(C, b)
        well_d = float(g['well']['depth'])
        max_z = max(max_z, C.surface_z(cx, cy) - (well_d - hh))
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
        out.export(path, file_type='stl')
        disk = trimesh.load(path, force='mesh')
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
    check_shape('xiao_usb_shell', shell, note='USB-C shell allowance near the port')
    reserved = {'xiao_nrf54l15': board_shape, 'xiao_usb_shell': shell}

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

    cell = C.cell()
    cell_shape = rbox(float(cell['width']), float(cell['length']), C.cell_h(),
                      3.5, 1.5, (float(cell['x']), float(cell['y']), C.cell_z()))
    check_shape('protected_cell', cell_shape)
    reserved['protected_cell'] = cell_shape
    metal_hits += probe_violation(cell_shape, keepout)[0]

    if p.get('oled'):
        oled = g['oled']
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
        sw_act = box(4.6, 4.6, act_h + 0.4, (-2.3, -2.3, -L - fl_h - act_h - 0.2))
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
        loc, _, _ = body.ray.intersects_location(ray_origins=[[sx, sy, 300.0]],
                                                 ray_directions=[[0, 0, -1]],
                                                 multiple_hits=True)
        zs = sorted(float(v) for v in loc[:, 2]) if len(loc) else []
        report['checks'][f"pilot_{sx}_{sy}_z"] = [round(z, 2) for z in zs]
        if not zs or zs[-1] < 0.5:
            pilot_ok = False
    if not pilot_ok:
        failures.append(f"{style}: pilot not blind")

    # lip engagement
    lip_probe = body.copy()
    v, d, h = probe_violation(lid, body, pitch=3.0)
    report['checks']['lid_body_collision_mm3'] = round(v, 3)
    if v > 40.0:
        failures.append(f"{style}: lid collides with body (~{v:.1f} mm3)")

    # ---- ergonomics -------------------------------------------------------
    bz = g['bezel']
    tilt = float(C.dash['tilt_deg']) if C.dash else 0.0
    ergo = {
        "layout": "flat tray + raised control deck, only the deck tilted",
        "dashboard_tilt_deg": tilt if C.dash else None,
        "flat_case_height_mm": round(C.lid_top(), 2),
        "max_height_mm": report['max_height_mm'],
        "screen_recess_acrylic_mm": round(bz['height'] - (bz['window_thickness'] - bz['seat_depth']), 2) if p.get('oled') else None,
        "screen_recess_glass_mm": round(float(g['oled']['seat_depth']) + bz['height'], 2) if p.get('oled') else None,
        "bezel_height_mm": bz['height'] if p.get('oled') else None,
        "hood_height_mm": bz['hood_height'] if p.get('oled') else None,
        "mount_back_flatness_mm": 0.0,
        "button_surface_mm": {},
        "plunger_top_vs_surface_mm": {},
        "assumed_eye_above_pod_mm": p.get('ergonomics', {}).get('eye_above_pod_mm'),
        "assumed_eye_outboard_mm": p.get('ergonomics', {}).get('eye_outboard_mm'),
        "sight_line_note": p.get('sight_line_note', ''),
        "switch_menu_keys": p.get('menu_keys', {}),
        "operating_hand": {b['id']: b.get('operating_hand', 'bare hand') for b in C.buttons()},
    }
    well_h = float(g['well']['depth'])
    for b in C.buttons():
        cx, cy = C.button_center(b)
        _h, _hd, hh = plunger_head_sizes(C, b)
        ergo['button_surface_mm'][b['id']] = round(C.surface_z(cx, cy), 2)
        ergo['plunger_top_vs_surface_mm'][b['id']] = round(-(well_h - hh), 2)
    if p.get('sidebar'):
        ergo['plunger_top_vs_surface_mm'][p['sidebar']['id']] = -0.2
    report['ergonomics'] = ergo
    for m in C.mounts():
        report['mounts'].append({"name": m['name'], "strap_width_mm": float(m['strap_width']),
                                 "layout": m.get('layout'), "loop_count": len(m['centers'])})

    report['checks']['failures'] = failures
    report['checks']['warnings'] = warnings
    report['checks']['all_passed'] = (len(failures) == 0)

    # preview items
    items = [(body, hex_rgb(palette['cyan'])), (lid, hex_rgb(palette['pink'])),
             (deck, hex_rgb(palette['cyan'])), (cap_asm, hex_rgb(palette['cyan']))]
    for i, b in enumerate(C.buttons(), start=1):
        stem = C.name(f"plunger_{b['id']}") if len(C.buttons()) > 1 else C.name(f"plunger_{i}")
        items.append((prints[stem][1], hex_rgb(palette['white'])))
    for m in C.mounts():
        items.append((build_carrier(C, m), hex_rgb(palette['cyan'])))
    if p.get('sidebar'):
        items.append((prints[C.name(f"plunger_{p['sidebar']['id']}")][1], hex_rgb(palette['pink'])))
    if p.get('bezel'):
        items.append((xform(build_bezel_local(C), bezel_matrix(C)), hex_rgb(palette['pink'])))
        items.append((xform(build_window_local(C), bezel_matrix(C)), (0.72, 0.86, 0.92)))
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
    if not args.only:
        for stale in glob.glob(os.path.join(EXPORTS_DIR, '*.stl')) + \
                     glob.glob(os.path.join(EXPORTS_DIR, '*.3mf')):
            try:
                os.remove(stale)
            except OSError:
                pass
    styles = [args.only] if args.only else ['receiver', 'wrist', 'keypad']
    palette = profiles['palette']

    t0 = time.time()
    dims = {"revision": profiles['revision'], "units": "mm",
            "generator": "cad/unbranded/generate_cases.py",
            "engine": ENGINE, "trimesh_version": trimesh.__version__,
            "hardware_measured": False,
            "parts": {}, "styles": {}, "fit_coupon": {}, "previews": {}, "validation": {}}
    failures, sheet, ergo_cases, scene_units = [], [], [], []

    for style in styles:
        C, report, prints, colors, items = build_style(profiles, style, EXPORTS_DIR, palette)
        dims['styles'][style] = report
        for stem, rep in report['parts'].items():
            dims['parts'][stem] = rep
        write_svg(C, os.path.join(EXPORTS_DIR, f"{style}_plan.svg"))
        for stem, (pm, _asm) in prints.items():
            prepare_export(pm).export(os.path.join(EXPORTS_DIR, stem + "_color.stl"),
                                      file_type='stl')
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
        ergo_cases.append(C)
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
    coupon.export(os.path.join(EXPORTS_DIR, "fit_coupon.stl"), file_type='stl')
    rep = mesh_report(coupon, "fit_coupon.stl")
    dims['fit_coupon'] = rep
    if not rep['watertight']:
        failures.append("fit_coupon: not watertight")
    sheet.append(("fit_coupon", coupon, palette['cyan'],
                  f"{inches(64)} x {inches(72)} x {inches(3)} in"))

    pal = {"revision": profiles['revision'],
           "colors": {k: palette[k] for k in ('cyan', 'pink', 'white')},
           "stl_color_support": False, "assemblies": {}}
    for style in styles:
        parts = []
        for stem, r in dims['styles'][style]['parts'].items():
            parts.append({"file": stem + "_color.stl",
                          "color": (palette['pink'] if ('lid' in stem or 'bezel' in stem)
                                    else palette['white'] if 'plunger' in stem and 'back' not in stem
                                    else palette['cyan']),
                          "bounds_mm": r['bounds_mm'], "components": r['components']})
        pal['assemblies'][style] = {"file": f"{style}_colored.3mf",
                                    "lid_print_file": f"{style}_lid_colored.3mf",
                                    "parts": parts, "stl_color_support": False}
    with open(os.path.join(EXPORTS_DIR, "palette.json"), 'w', encoding='utf-8') as fh:
        json.dump(pal, fh, indent=2)

    dims['validation'] = {
        "all_parts_watertight": all(v['watertight'] for v in dims['parts'].values()),
        "all_parts_on_bed": all(v['on_bed'] for v in dims['parts'].values()),
        "all_parts_single_shell": all(v['components'] == 1 for v in dims['parts'].values()),
        "all_volumes_positive": all(v['volume_mm3'] > 0 for v in dims['parts'].values()),
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
        render_mesh_array(scene, 1560, 700, ss=2).save(os.path.join(HERE, "preview.png"))
        render_part_sheet(sheet, os.path.join(HERE, "parts-preview.png"), cols=4)
        mount_cells = []
        for C, _items, prints_ in scene_units:
            for m in C.mounts():
                stem = C.name(f"{m['name']}_carrier")
                pm = prints_[stem][0]
                mount_cells.append((stem, pm, palette['cyan'],
                                    f"{inches(pm.extents[0])} x {inches(pm.extents[1])} x "
                                    f"{inches(pm.extents[2])} in, {m['strap_width']:g} mm strap"))
        render_part_sheet(mount_cells, os.path.join(HERE, "mounts-preview.png"), cols=3)
        render_ergonomics(ergo_cases, os.path.join(HERE, "ergonomics-preview.png"))
        dims['previews'] = {
            "method": "built-in software z-buffer renderer (numpy) + Pillow labels; "
                      "trimesh scene.save_image needs pyglet, which is not installed",
            "files": ["preview.png", "parts-preview.png", "mounts-preview.png",
                      "ergonomics-preview.png"],
            "render_seconds": round(time.time() - tp, 2)}
        print(f"[preview] sheets written in {time.time() - tp:.1f}s")

    with open(os.path.join(EXPORTS_DIR, "dimensions.json"), 'w', encoding='utf-8') as fh:
        json.dump(dims, fh, indent=2)
    print(f"wrote dimensions.json in {time.time() - t0:.1f}s")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print("all checks passed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
