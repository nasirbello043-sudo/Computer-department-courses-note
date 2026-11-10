"""Draws graph, conic and parametric diagrams as black-and-white PNG images for the PDF courses."""
import math, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SAFE = {"sin": np.sin, "cos": np.cos, "tan": np.tan, "exp": np.exp, "log": np.log, "sqrt": np.sqrt,
        "abs": np.abs, "pi": math.pi, "e": math.e}

def _expr(text, var_values):
    src = str(text).replace("^", "**")
    env = dict(SAFE); env.update(var_values)
    with np.errstate(all="ignore"):
        return eval(src, {"__builtins__": {}}, env)

def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default

def _setup(title):
    fig, ax = plt.subplots(figsize=(5.2, 4.2), dpi=150)
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, color="0.82", linewidth=0.6)
    ax.axhline(0, color="black", linewidth=0.8); ax.axvline(0, color="black", linewidth=0.8)
    ax.set_title(title, fontsize=11, color="black")
    for s in ax.spines.values():
        s.set_color("black")
    ax.tick_params(colors="black", labelsize=8)
    return fig, ax

def render_graph(g, path):
    xmin, xmax = _num(g.get("xmin"), -5), _num(g.get("xmax"), 5)
    xs = np.linspace(xmin, xmax, 800)
    ys = _expr(g.get("fn", "x"), {"x": xs})
    ys = np.where(np.abs(ys) > 1e6, np.nan, ys)
    fig, ax = _setup(g.get("title", ""))
    ax.plot(xs, ys, color="black", linewidth=1.6)
    for p in g.get("points", []) or []:
        ax.plot(_num(p.get("x")), _num(p.get("y")), "o", markerfacecolor="white" if p.get("open") else "black",
                markeredgecolor="black", markersize=6)
        if p.get("label"):
            ax.annotate(str(p["label"]), (_num(p.get("x")), _num(p.get("y"))), xytext=(6, 6), textcoords="offset points", fontsize=8)
    fig.text(0.5, 0.01, g.get("caption", ""), ha="center", fontsize=8)
    fig.savefig(path, facecolor="white", bbox_inches="tight"); plt.close(fig)
    return path

def render_conic(g, path):
    h, k = _num(g.get("h")), _num(g.get("k"))
    shape = str(g.get("shape", "circle")).lower()
    t = np.linspace(0, 2 * math.pi, 600)
    vertical = str(g.get("orientation", "horizontal")).lower() == "vertical"
    fig, ax = _setup(g.get("title", shape.title()))
    if shape == "circle":
        r = _num(g.get("r"), 1)
        ax.plot(h + r * np.cos(t), k + r * np.sin(t), color="black", linewidth=1.6)
        ax.plot(h, k, "o", color="black", markersize=4)
    elif shape == "ellipse":
        a, b = _num(g.get("a"), 2), _num(g.get("b"), 1)
        if vertical: a, b = b, a
        ax.plot(h + a * np.cos(t), k + b * np.sin(t), color="black", linewidth=1.6)
        c = math.sqrt(max(0.0, max(a, b) ** 2 - min(a, b) ** 2))
        dx, dy = (c, 0) if not vertical else (0, c)
        for sx in (-1, 1):
            ax.plot(h + sx * dx, k + sx * dy, "x", color="black", markersize=7)
    elif shape == "parabola":
        p = abs(_num(g.get("p"), 1))
        d = str(g.get("orientation", "right")).lower()
        s = np.linspace(-4 * p - 2, 4 * p + 2, 600)
        if d in ("right", "left"):
            x = s * s / (4 * p) * (1 if d == "right" else -1); ax.plot(h + x, k + s, color="black", linewidth=1.6)
            ax.plot(h + (p if d == "right" else -p), k, "x", color="black", markersize=7)
        else:
            y = s * s / (4 * p) * (1 if d == "up" else -1); ax.plot(h + s, k + y, color="black", linewidth=1.6)
            ax.plot(h, k + (p if d == "up" else -p), "x", color="black", markersize=7)
    else:  # hyperbola
        a, b = _num(g.get("a"), 2), _num(g.get("b"), 1)
        u = np.linspace(-2.5, 2.5, 600)
        if vertical:
            ax.plot(h + b * np.sinh(u), k + a * np.cosh(u), color="black", linewidth=1.6)
            ax.plot(h + b * np.sinh(u), k - a * np.cosh(u), color="black", linewidth=1.6)
        else:
            ax.plot(h + a * np.cosh(u), k + b * np.sinh(u), color="black", linewidth=1.6)
            ax.plot(h - a * np.cosh(u), k + b * np.sinh(u), color="black", linewidth=1.6)
    fig.text(0.5, 0.01, g.get("caption", ""), ha="center", fontsize=8)
    fig.savefig(path, facecolor="white", bbox_inches="tight"); plt.close(fig)
    return path

def render_parametric(g, path):
    t = np.linspace(_num(g.get("tmin"), 0), _num(g.get("tmax"), 2 * math.pi), 800)
    x = np.broadcast_to(_expr(g.get("x", "t"), {"t": t}), t.shape)
    y = np.broadcast_to(_expr(g.get("y", "t"), {"t": t}), t.shape)
    fig, ax = _setup(g.get("title", ""))
    ax.plot(x, y, color="black", linewidth=1.6)
    for tm in g.get("marks", []) or []:
        xm = _expr(g.get("x", "t"), {"t": _num(tm)}); ym = _expr(g.get("y", "t"), {"t": _num(tm)})
        ax.plot(float(xm), float(ym), "o", color="black", markersize=5)
        ax.annotate(f"t={tm}", (float(xm), float(ym)), xytext=(5, 5), textcoords="offset points", fontsize=8)
    fig.text(0.5, 0.01, g.get("caption", ""), ha="center", fontsize=8)
    fig.savefig(path, facecolor="white", bbox_inches="tight"); plt.close(fig)
    return path

def render_figure(g, path):
    """Returns the PNG path, or None if the figure type is not one of the drawable kinds."""
    kind = g.get("type")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        if kind == "graph": return render_graph(g, path)
        if kind == "conic": return render_conic(g, path)
        if kind == "parametric": return render_parametric(g, path)
    except Exception as e:  # a bad figure must never stop the course
        print("Figure could not be drawn:", kind, g.get("title"), "-", e)
    return None
