"""bmesh-based geometry helpers (run inside Blender).

``MeshBuilder`` accumulates primitives into one bmesh with per-face material
indices and per-vertex bone weights, then emits a single mesh object whose
vertex groups match the rig's bone names (rigid/blended skinning).
"""
from __future__ import annotations

import math
from typing import Callable

import bmesh
import bpy
from mathutils import Matrix, Vector

Weights = dict | Callable[[Vector], dict] | None


def frame_matrix(center, normal, scale=(1.0, 1.0, 1.0)) -> Matrix:
    """Matrix whose local +Y points along ``normal`` (world Z stays 'up')."""
    n = Vector(normal).normalized()
    up = Vector((0, 0, 1))
    if abs(n.dot(up)) > 0.98:
        up = Vector((0, -1, 0))
    x = n.cross(up).normalized()
    z = x.cross(n).normalized()
    rot = Matrix((x, n, z)).transposed().to_4x4()
    return Matrix.Translation(Vector(center)) @ rot @ Matrix.Diagonal((*scale, 1.0))


def segment_matrix(p0, p1) -> tuple[Matrix, float]:
    """Matrix placing a Z-aligned primitive between two points; returns (matrix, length)."""
    a, b = Vector(p0), Vector(p1)
    d = b - a
    length = d.length
    q = Vector((0, 0, 1)).rotation_difference(d.normalized() if length > 1e-9 else Vector((0, 0, 1)))
    return Matrix.Translation((a + b) / 2) @ q.to_matrix().to_4x4(), length


class MeshBuilder:
    def __init__(self, name: str):
        self.name = name
        self.bm = bmesh.new()
        self.deform = self.bm.verts.layers.deform.verify()
        # Integer tag per vertex (saved as mesh attribute "part"). bmesh reuses freed
        # element slots, so vertex indices are not creation-ordered; tags are reliable.
        self.part = self.bm.verts.layers.int.new("part")
        self.tag = 0
        self.materials: list[bpy.types.Material] = []
        self.groups: list[str] = []

    # -- bookkeeping -----------------------------------------------------------
    def _mat(self, mat) -> int:
        if mat not in self.materials:
            self.materials.append(mat)
        return self.materials.index(mat)

    def _grp(self, name: str) -> int:
        if name not in self.groups:
            self.groups.append(name)
        return self.groups.index(name)

    def _finish(self, verts, mat, weights: Weights, smooth: bool = True) -> list:
        verts = list(verts)
        idx = self._mat(mat)
        for v in verts:
            v[self.part] = self.tag
        faces = {f for v in verts for f in v.link_faces}
        for f in faces:
            f.material_index = idx
            f.smooth = smooth
        if weights is not None:
            for v in verts:
                w = weights(v.co) if callable(weights) else weights
                for bone, val in w.items():
                    if val > 1e-4:
                        v[self.deform][self._grp(bone)] = float(val)
        return verts

    # -- primitives ------------------------------------------------------------
    def sphere(self, center, radii, mat, weights: Weights = None, segs: int = 20, rings: int = 12,
               matrix: Matrix | None = None):
        m = matrix if matrix is not None else Matrix.Translation(Vector(center)) @ Matrix.Diagonal((*radii, 1.0))
        res = bmesh.ops.create_uvsphere(self.bm, u_segments=segs, v_segments=rings, radius=1.0, matrix=m)
        return self._finish(res["verts"], mat, weights)

    def capsule(self, p0, p1, r0, r1, mat, weights: Weights = None, segs: int = 14, caps: bool = True):
        m, length = segment_matrix(p0, p1)
        res = bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=segs, radius1=r0,
                                    radius2=r1, depth=max(length, 1e-4), matrix=m)
        verts = self._finish(res["verts"], mat, weights)
        if caps:
            verts += self.sphere(p0, (r0, r0, r0), mat, weights, segs=segs, rings=8)
            verts += self.sphere(p1, (r1, r1, r1), mat, weights, segs=segs, rings=8)
        return verts

    def cylinder(self, center, radius, depth, mat, weights: Weights = None, segs: int = 16,
                 matrix: Matrix | None = None, radius2: float | None = None):
        m = matrix if matrix is not None else Matrix.Translation(Vector(center))
        res = bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=segs, radius1=radius,
                                    radius2=radius if radius2 is None else radius2, depth=depth, matrix=m)
        return self._finish(res["verts"], mat, weights)

    def box(self, center, size, mat, weights: Weights = None, matrix: Matrix | None = None):
        m = matrix if matrix is not None else Matrix.Translation(Vector(center)) @ Matrix.Diagonal((*size, 1.0))
        res = bmesh.ops.create_cube(self.bm, size=1.0, matrix=m)
        return self._finish(res["verts"], mat, weights, smooth=False)

    def torus(self, center, major: float, minor: float, mat, weights: Weights = None, segs: int = 24,
              ring_segs: int = 8, matrix: Matrix | None = None, scale=(1.0, 1.0, 1.0)):
        """Torus lying in the XY plane (before ``matrix``)."""
        m = matrix if matrix is not None else Matrix.Translation(Vector(center)) @ Matrix.Diagonal((*scale, 1.0))
        grid = []
        for i in range(segs):
            a = 2 * math.pi * i / segs
            row = []
            for j in range(ring_segs):
                b = 2 * math.pi * j / ring_segs
                r = major + minor * math.cos(b)
                row.append(self.bm.verts.new(m @ Vector((r * math.cos(a), r * math.sin(a), minor * math.sin(b)))))
            grid.append(row)
        for i in range(segs):
            for j in range(ring_segs):
                a, b = grid[i][j], grid[(i + 1) % segs][j]
                c, d = grid[(i + 1) % segs][(j + 1) % ring_segs], grid[i][(j + 1) % ring_segs]
                self.bm.faces.new((a, b, c, d))
        return self._finish([v for row in grid for v in row], mat, weights)

    def grid(self, rows: int, cols: int, point_fn: Callable[[float, float], Vector], mat,
             weights: Weights = None):
        """Open surface sampled from ``point_fn(u, v)`` for u, v in [0, 1]."""
        verts = [[self.bm.verts.new(point_fn(j / cols, i / rows)) for j in range(cols + 1)] for i in range(rows + 1)]
        for i in range(rows):
            for j in range(cols):
                self.bm.faces.new((verts[i][j], verts[i][j + 1], verts[i + 1][j + 1], verts[i + 1][j]))
        return self._finish([v for row in verts for v in row], mat, weights)

    def delete(self, verts) -> None:
        bmesh.ops.delete(self.bm, geom=list(verts), context="VERTS")

    # -- output ----------------------------------------------------------------
    def to_object(self, collection, parent=None) -> bpy.types.Object:
        self.bm.normal_update()
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces[:])
        mesh = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(mesh)
        self.bm.free()
        for m in self.materials:
            mesh.materials.append(m)
        obj = bpy.data.objects.new(self.name, mesh)
        collection.objects.link(obj)
        for g in self.groups:
            obj.vertex_groups.new(name=g)
        if parent is not None:
            obj.parent = parent
        return obj
