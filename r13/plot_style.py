"""Reusable publication plotting; no data transforms or axis-limit changes."""
from contextlib import contextmanager
from pathlib import Path
import warnings
import matplotlib as mpl
from matplotlib import font_manager
from cycler import cycler

MATLAB_COLORS = [
    (0.0000, 0.4470, 0.7410), (0.8500, 0.3250, 0.0980),
    (0.9290, 0.6940, 0.1250), (0.4940, 0.1840, 0.5560),
    (0.4660, 0.6740, 0.1880), (0.3010, 0.7450, 0.9330),
    (0.6350, 0.0780, 0.1840),
]
WIDTHS_CM = {"single-column": 8.5, "medium": 13.5, "double-column": 17.5}


def resolve_font(requested=None):
    """Resolve real regular/italic/bold faces without default substitution."""
    candidates = [requested] if requested else [
        "Arial", "Helvetica", "Liberation Sans", "Nimbus Sans", "DejaVu Sans"
    ]
    for family in candidates:
        try:
            for style, weight in [("normal", "normal"), ("italic", "normal"),
                                  ("normal", "bold")]:
                path = font_manager.findfont(
                    font_manager.FontProperties(family=[family], style=style, weight=weight),
                    fallback_to_default=False,
                )
                face = font_manager.get_font(path)
                if style == "italic" and not getattr(face.style_flags, "value", face.style_flags) & 1:
                    raise ValueError("Italic face unavailable")
                if weight == "bold" and not getattr(face.style_flags, "value", face.style_flags) & 2:
                    raise ValueError("Bold face unavailable")
            if not requested and family != "Arial":
                warnings.warn("Arial unavailable; using %s for this figure set." % family,
                              UserWarning, stacklevel=2)
            return family
        except ValueError:
            continue
    raise ValueError("Required font faces unavailable: %s" % ", ".join(candidates))


@contextmanager
def paper_style(font=None, overrides=None):
    """Create AND export inside this context; restore caller settings."""
    family = resolve_font(font)
    params = {
        "font.family": [family], "font.size": 8,
        "axes.labelsize": 8, "axes.titlesize": 9,
        "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
        "mathtext.fontset": "custom", "mathtext.rm": family,
        "mathtext.it": family + ":italic", "mathtext.bf": family + ":bold",
        "mathtext.sf": family, "mathtext.default": "it",
        "mathtext.cal": "STIXNonUnicode:italic",
        "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none",
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "savefig.transparent": False,
        "text.color": "#222222", "axes.edgecolor": "#222222",
        "axes.labelcolor": "#222222", "xtick.color": "#222222",
        "ytick.color": "#222222", "axes.linewidth": 0.65,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": False, "axes.axisbelow": True,
        "grid.linewidth": 0.4, "grid.color": "#b0b0b0", "grid.alpha": 0.25,
        "xtick.direction": "out", "ytick.direction": "out",
        "xtick.major.size": 3, "ytick.major.size": 3,
        "xtick.major.width": 0.65, "ytick.major.width": 0.65,
        "xtick.minor.width": 0.5, "ytick.minor.width": 0.5,
        "xtick.top": False, "ytick.right": False,
        "lines.linewidth": 1.5, "lines.markersize": 4,
        "lines.markeredgewidth": 0.65, "legend.frameon": False,
        "legend.handlelength": 2.6, "legend.borderaxespad": 0.4,
        "axes.prop_cycle": cycler(color=MATLAB_COLORS),
        "figure.constrained_layout.use": True,
        "figure.constrained_layout.w_pad": 0.045,
        "figure.constrained_layout.h_pad": 0.045,
        "figure.constrained_layout.wspace": 0.06,
        "figure.constrained_layout.hspace": 0.06,
        "savefig.dpi": 300, "savefig.bbox": None,
    }
    if overrides:
        params.update(overrides)
    with mpl.rc_context(params):
        yield family


def figure_size(preset="single-column", height_cm=None):
    width = WIDTHS_CM[preset]
    height = width * 0.70 if height_cm is None else float(height_cm)
    if not height > 0 or not height < float("inf"):
        raise ValueError("height_cm must be finite and positive")
    return width / 2.54, height / 2.54


def series_styles(model_order):
    """Create once for the paper; reuse this mapping for every subset."""
    names = list(model_order)
    if len(names) != len(set(names)):
        raise ValueError("Model names must be unique")
    if len(names) > 28:
        raise ValueError("More than 28 series: use separate panels")
    line_styles = ["-", "--", "-.", ":"]
    markers = ["o", "s", "^", "D", "v", "P", "X"]
    return {
        name: dict(color=MATLAB_COLORS[i % 7], linestyle=line_styles[i % 4],
                   marker=markers[i % 7], markerfacecolor="white",
                   markeredgecolor="#333333")
        for i, name in enumerate(names)
    }


def label_panels(axes, uppercase=False, xy=(0.0, 1.04)):
    """Pass data axes only, excluding colorbars; reserve space above plots."""
    import numpy as np
    flat = np.asarray(axes, dtype=object).ravel()
    if len(flat) > 26:
        raise ValueError("Use at most 26 labeled panels")
    for i, ax in enumerate(flat):
        label = chr(65 + i) if uppercase else "(%s)" % chr(97 + i)
        ax.text(*xy, label, transform=ax.transAxes, ha="left", va="bottom",
                fontsize=9.5, fontweight="bold", clip_on=False, in_layout=True)


def export_figure(fig, stem, formats=("pdf", "png"), dpi=300,
                  tight=False, overwrite=False):
    """Preserve physical size by default; reject existing destinations."""
    stem = Path(stem)
    formats = tuple(formats)
    if not formats or any(fmt not in {"pdf", "svg", "png", "eps"} for fmt in formats):
        raise ValueError("Use pdf, svg, png or eps")
    if len(set(formats)) != len(formats):
        raise ValueError("Duplicate output formats")
    paths = [stem.parent / (stem.name + "." + fmt) for fmt in formats]
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        raise FileExistsError("Choose a new stem or authorize overwrite: " + ", ".join(existing))
    stem.parent.mkdir(parents=True, exist_ok=True)
    fig.canvas.draw()
    for path in paths:
        fig.savefig(str(path), dpi=dpi, bbox_inches="tight" if tight else None,
                    facecolor="white", transparent=False)
    return paths

