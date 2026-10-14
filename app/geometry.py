"""Плоская геометрия в метрах. Поворот положителен по часовой стрелке (ось Y вниз)."""
from math import cos, sin, radians, hypot

EPS = 1e-8


def xy(point):
    return (point.x, point.y) if hasattr(point, "x") else tuple(point)


def edges(poly):
    return zip(poly, poly[1:] + poly[:1])


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def project(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0 if length2 < EPS * EPS else max(0, min(1, ((p[0]-a[0])*dx + (p[1]-a[1])*dy)/length2))
    return a[0] + t * dx, a[1] + t * dy


def on_segment(p, a, b):
    q = project(p, a, b)
    return hypot(p[0] - q[0], p[1] - q[1]) <= EPS


def intersection_parameters(a, b, c, d):
    """Параметры t точек пересечения на отрезке a→b, включая наложение."""
    rx, ry, sx, sy = b[0]-a[0], b[1]-a[1], d[0]-c[0], d[1]-c[1]
    det = rx * sy - ry * sx
    if abs(det) > EPS:
        t = ((c[0]-a[0])*sy - (c[1]-a[1])*sx) / det
        u = ((c[0]-a[0])*ry - (c[1]-a[1])*rx) / det
        return [max(0, min(1, t))] if -EPS <= t <= 1+EPS and -EPS <= u <= 1+EPS else []
    if abs(cross(a, b, c)) > EPS:
        return []
    length2 = rx*rx + ry*ry
    if length2 < EPS*EPS:
        return [0] if on_segment(a, c, d) else []
    ts = [((p[0]-a[0])*rx + (p[1]-a[1])*ry)/length2 for p in (c, d)]
    lo, hi = max(0, min(ts)), min(1, max(ts))
    return [lo, hi] if lo <= hi+EPS else []


def segment_distance(a, b, c, d):
    intersections = intersection_parameters(a, b, c, d)
    if intersections:
        t = intersections[0]
        p = (a[0] + t*(b[0]-a[0]), a[1] + t*(b[1]-a[1]))
        return 0.0, p, p
    candidates = [(a, project(a, c, d)), (b, project(b, c, d)),
                  (project(c, a, b), c), (project(d, a, b), d)]
    p, q = min(candidates, key=lambda pair: hypot(pair[0][0]-pair[1][0], pair[0][1]-pair[1][1]))
    return hypot(p[0]-q[0], p[1]-q[1]), p, q


def point_inside(p, poly):
    if any(on_segment(p, a, b) for a, b in edges(poly)):
        return True
    inside = False
    for a, b in edges(poly):
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1]-a[1])*(b[0]-a[0])/(b[1]-a[1])
            if p[0] < x:
                inside = not inside
    return inside


def boundary_distance(a, b):
    return min((segment_distance(p, q, r, s) for p, q in edges(a) for r, s in edges(b)), key=lambda x: x[0])


def polygon_distance(a, b):
    for p in a:
        if point_inside(p, b):
            return 0.0, p, p
    for p in b:
        if point_inside(p, a):
            return 0.0, p, p
    return boundary_distance(a, b)


def point_polygon_distance(p, poly, boundary=False):
    if not boundary and point_inside(p, poly):
        return 0.0, p, p
    qs = [project(p, a, b) for a, b in edges(poly)]
    q = min(qs, key=lambda q: hypot(p[0]-q[0], p[1]-q[1]))
    return hypot(p[0]-q[0], p[1]-q[1]), p, q


def polygon_contains(outer, inner):
    if not all(point_inside(p, outer) for p in inner):
        return False
    # В вогнутом участке вершины могут лежать внутри, а ребро — пересекать выемку.
    for a, b in edges(inner):
        ts = [0.0, 1.0]
        for c, d in edges(outer):
            ts.extend(intersection_parameters(a, b, c, d))
        ts = sorted(set(ts))
        for lo, hi in zip(ts, ts[1:]):
            t = (lo+hi)/2
            if not point_inside((a[0]+t*(b[0]-a[0]), a[1]+t*(b[1]-a[1])), outer):
                return False
    return True


def validate_polygon(poly):
    if len(set(poly)) != len(poly):
        raise ValueError("Вершины участка должны быть различными; последнюю точку не повторяйте.")
    if abs(sum(a[0]*b[1]-b[0]*a[1] for a, b in edges(poly))) < EPS:
        raise ValueError("Участок должен иметь ненулевую площадь.")
    n = len(poly)
    for i, (a, b) in enumerate(edges(poly)):
        if hypot(a[0]-b[0], a[1]-b[1]) < EPS:
            raise ValueError("Ребро участка слишком короткое.")
        prev, nxt = poly[(i-1) % n], poly[(i+1) % n]
        if abs(cross(prev, a, nxt)) < EPS and (on_segment(nxt, prev, a) or on_segment(prev, a, nxt)):
            raise ValueError("Рёбра участка накладываются друг на друга.")
        for j, (c, d) in enumerate(edges(poly)):
            if j <= i or j == i+1 or (i == 0 and j == n-1):
                continue
            if intersection_parameters(a, b, c, d):
                raise ValueError("Граница участка пересекает сама себя.")


def footprint(obj):
    angle = radians(obj.angle)
    co, si = cos(angle), sin(angle)
    return [(obj.x + dx*co - dy*si, obj.y + dx*si + dy*co)
            for dx, dy in [(-obj.width/2, -obj.height/2), (obj.width/2, -obj.height/2),
                           (obj.width/2, obj.height/2), (-obj.width/2, obj.height/2)]]


def area(poly):
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a, b in edges(poly)))/2
