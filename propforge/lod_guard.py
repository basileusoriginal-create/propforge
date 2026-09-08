"""Geometry-only protection rules shared by Blender builds and regression tests.

These conservative guards are not a visual quality certificate. Reduction may
use more triangles than requested to retain contact points and narrow parts.
"""
from __future__ import annotations

import math


def protected_vertices(points, edges, triangles):
    if not points:
        raise ValueError("Leeres Mesh")
    if len(triangles) <= 64:
        return set(range(len(points)))
    bottom = min(p[2] for p in points)
    protected = {i for i, p in enumerate(points) if p[2] <= bottom + 0.001}
    adjacent = [set() for _ in points]
    for a, b in edges:
        adjacent[a].add(b)
        adjacent[b].add(a)
    remaining = set(range(len(points)))
    while remaining:
        todo = [remaining.pop()]
        component = set(todo)
        while todo:
            for vertex in adjacent[todo.pop()] & remaining:
                remaining.remove(vertex)
                component.add(vertex)
                todo.append(vertex)
        extents = sorted(max(points[j][i] for j in component) - min(points[j][i] for j in component)
                         for i in range(3))
        # A rod has TWO small axes. A broad thin tabletop is not a rod.
        slender = extents[1] <= 0.08 and extents[2] >= 4 * max(extents[1], 1e-8)
        contact = any(j in protected for j in component)
        if (slender and len(component) <= 256) or (contact and len(component) <= 128):
            protected.update(component)
    return protected


def finite_bounds(points):
    if not points or not all(math.isfinite(c) for p in points for c in p):
        raise ValueError("Leere/nicht endliche Geometrie")
    return {"min": [min(p[i] for p in points) for i in range(3)],
            "max": [max(p[i] for p in points) for i in range(3)]}
