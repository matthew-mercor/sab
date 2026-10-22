#!/usr/bin/env python3
"""Build topdown_comparison.png: scorer-aligned top-down panels, one per qualifying rollout.

Each panel shows the answer-key furniture (pale) and the run's graded scene (bold) in the
scorer's own aligned frame: colour identifies the item, pale = original, bold = reconstruction,
grey = unmapped model geometry (e.g. rollout2's TMP_FLOOR). Colour is item identity, NOT error
magnitude. One whole-scene similarity alignment per run, exactly as the verifier computes it.

Coordinates come from tooling/analyze_rollout.py's pipeline (per-node surface samples, rng 0,
icp_sim3 + umeyama_sim3 from tooling/scorer/metrics.py). The script ABORTS if the reproduced
obj_f@5%_nn differs from a panel's score.json reward by > 1e-6 — no rounded-metadata transforms.

Layout follows the supplied comparison-sheet example: small left-aligned captions above each
panel (run + reward on the first line, the verified scale/yaw/tilt in subdued red on the
second), furniture labels near the original items, a light metre grid, and a compact
bottom-left legend. Headings, captions, plots, and legend each get reserved space.

Usage (from the repo's SceneActBench-Final directory):

    python tooling/make_topdown_comparison.py \
        --task tasks/recon-designer-bedroom-4item \
        --panel "rollout 1:results/kimi-k3/recon-designer-bedroom-4item/rollout1" \
        --panel "rollout 2:results/kimi-k3/recon-designer-bedroom-4item/rollout2" \
        --panel "rollout 3:results/kimi-k3/recon-designer-bedroom-4item/rollout3" \
        -o results/kimi-k3/recon-designer-bedroom-4item/topdown_comparison.png

For the standalone high-resolution file, add a small heading and the fuller legend:

    python tooling/make_topdown_comparison.py ... \
        --title "Designer bedroom — TOP-DOWN as the scorer sees each rollout (after aligning the whole room)" \
        --full-legend -o results/kimi-k3/recon-designer-bedroom-4item/topdown_comparison.png

Append the compact version to the comparison sheet with tooling/make_rollouts_vs_golden.py
(see that script's docstring).

Other samples: --item-colors overrides the bedroom colour set (legend order follows the
JSON key order), --axis-note / --unmapped-note override the bedroom-specific footnote
texts, and --empty-panel "label:score.json:note" adds a panel for a run that produced
no scene: the pale answer key underlay only, a centred no-output message, and the note
in subdued red (the reward is read from the given score.json, never typed in).
"""
import argparse
import json
import os
import sys
import textwrap

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_rollout as AR  # noqa: E402  (brings in metrics as AR.M)

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

# consistent furniture colours across panels (colour = item identity, not error)
ITEM_COLORS = {"Bed": (0.0, 0.51, 0.78), "Side_Table": (0.24, 0.71, 0.29),
               "Bedside_Table": (0.96, 0.51, 0.19), "Ottoman": (0.57, 0.12, 0.71)}
LEGEND_ORDER = ["Bed", "Side_Table", "Bedside_Table", "Ottoman"]
UNMAPPED_COLOR = (0.45, 0.45, 0.45)
UNMAPPED_PALE = (0.82, 0.82, 0.82)
MAX_PTS_PER_GROUP = 20000  # display cap only (rng 42); alignment/scores use full clouds

DARK = (0.16, 0.20, 0.30)          # near-black slate for captions
SUBDUED_RED = (0.62, 0.16, 0.16)   # transform line, as in the layout example


def pale(c, amount=0.78):
    """Lighter tint of an item colour for the original furniture underlay."""
    return tuple(v + (1.0 - v) * amount for v in c)


def uminus(text):
    """Typographic minus for negative numbers (matches the example's style)."""
    return text.replace("-", "−")


def run_alignment(run_dir, golden_dir):
    """Exact analyzer pipeline; returns (aligned points, tags, parts, alignment dict, reward)."""
    glb = os.path.join(run_dir, "agent_scene.glb")
    item_map = json.load(open(os.path.join(run_dir, "item_map.json")))
    score = json.load(open(os.path.join(run_dir, "score.json")))

    tagged = AR.per_node_samples(glb)
    P = np.vstack([p for _, p in tagged])
    tags = np.concatenate([np.full(len(p), n) for n, p in tagged])
    Q, parts = AR.M.load_gt_furniture(golden_dir)

    rng = np.random.default_rng(0)
    Ps = P[rng.choice(len(P), 4000, False)] if len(P) > 4000 else P
    Pa, Qs = AR.M.icp_sim3(Ps, Q, sample=4000, rng=rng)
    s_al, R_al, t_al = AR.M.umeyama_sim3(Ps, Pa)
    P_full = (s_al * (R_al @ P.T)).T + t_al

    lab = AR.nn_partition(P_full, parts)
    repro = AR.per_item_f(P_full, parts, lab)
    repro_reward = float(np.mean([r["f@5%"] for r in repro]))
    if abs(repro_reward - score["reward"]) > 1e-6:
        raise SystemExit(f"{run_dir}: repro mismatch {repro_reward:.10f} vs "
                         f"score.json {score['reward']:.10f}")

    yaw = float(np.degrees(np.arctan2(R_al[1, 0], R_al[0, 0])))
    z_rot = R_al @ np.array([0, 0, 1.0])
    tilt = float(np.degrees(np.arccos(np.clip(z_rot[2], -1, 1))))
    align = {"scale": float(s_al), "yaw_deg": yaw, "tilt_deg": tilt}
    node2item = {n: it for it, nodes in item_map.items() for n in nodes}
    return P_full, tags, node2item, parts, align, float(score["reward"])


def decim(pts, rng):
    if len(pts) > MAX_PTS_PER_GROUP:
        pts = pts[rng.choice(len(pts), MAX_PTS_PER_GROUP, False)]
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--panel", action="append", required=True, help="'label:run_dir'; repeatable")
    ap.add_argument("--empty-panel", action="append", default=[],
                    help="'label:score.json:note' — panel for a run that produced no scene: "
                         "pale answer key only, centred no-output message, note in subdued "
                         "red; reward read from score.json; repeatable")
    ap.add_argument("--item-colors", default=None,
                    help="JSON object (or @file) mapping item name to [r, g, b] 0-1; legend "
                         "order follows the key order (default: the designer-bedroom set)")
    ap.add_argument("--label-offsets", default=None,
                    help="JSON object (or @file) mapping item name to [dx, dy] in metres, "
                         "added to its furniture label position (default: no offsets)")
    ap.add_argument("--axis-note", default=None, help="override the bottom axis-orientation note")
    ap.add_argument("--unmapped-note", default=None,
                    help="override the --full-legend unmapped-geometry note")
    ap.add_argument("--title", default=None,
                    help="optional small left-aligned heading drawn above the panels "
                         "(standalone file; the sheet supplies its own heading instead)")
    ap.add_argument("--full-legend", action="store_true",
                    help="two-line legend with the unmapped-geometry note (standalone file)")
    ap.add_argument("--title-fontsize", type=float, default=13.0,
                    help="heading font size (default 13; reduce for narrow single-panel figures)")
    ap.add_argument("--legend-ncol", type=int, default=None,
                    help="legend columns (default: a single row with all entries)")
    ap.add_argument("--wrap-notes", type=int, default=None, metavar="CHARS",
                    help="wrap the footer notes at CHARS characters per line and stack them "
                         "above the bottom edge, legend above them (for narrow single-panel "
                         "figures; default: single unwrapped lines)")
    ap.add_argument("--figsize", nargs=2, type=float, default=None, metavar=("W", "H"),
                    help="figure size in inches at 170 dpi (default: 4.9 per panel wide, "
                         "5.9 with --title else 5.55 high) — e.g. --figsize 9 8.5 gives the "
                         "1530x1445 single-panel presentation canvas")
    ap.add_argument("--axes-rect", nargs=4, type=float, default=None,
                    metavar=("LEFT", "BOTTOM", "WIDTH", "HEIGHT"),
                    help="axes rectangle in figure fractions (single-panel figures only; "
                         "default: the subplots_adjust band left=0.038 right=0.995 "
                         "top=0.862/0.895 bottom=0.185)")
    ap.add_argument("--title-y", type=float, default=0.962,
                    help="title baseline in figure fractions (default 0.962)")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    golden_dir = os.path.join(a.task, "tests", "golden")

    item_colors, legend_order = ITEM_COLORS, LEGEND_ORDER
    if a.item_colors:
        spec = a.item_colors
        if spec.startswith("@"):
            spec = open(spec[1:]).read()
        item_colors = {k: tuple(v) for k, v in json.loads(spec).items()}
        legend_order = list(item_colors)
    label_offsets = {}
    if a.label_offsets:
        spec = a.label_offsets
        if spec.startswith("@"):
            spec = open(spec[1:]).read()
        label_offsets = {k: tuple(v) for k, v in json.loads(spec).items()}

    runs = []
    for spec in a.panel:
        label, run_dir = spec.split(":", 1)
        runs.append(("run", label) + run_alignment(run_dir, golden_dir))
    for spec in a.empty_panel:
        label, rest = spec.split(":", 1)
        score_path, note = rest.split(":", 1)
        reward = float(json.load(open(score_path))["reward"])
        runs.append(("empty", label, reward, note.strip()))

    # common square limits: union of golden + every run's aligned cloud, padded; no cropping
    Q_gold, gold_parts = AR.M.load_gt_furniture(golden_dir)
    all_xy = [Q_gold[:, :2]] + [r[2][:, :2] for r in runs if r[0] == "run"]
    xy = np.vstack(all_xy)
    lo, hi = xy.min(0) - 0.3, xy.max(0) + 0.3
    ctr, half = (lo + hi) / 2, (hi - lo).max() / 2
    xlim = (ctr[0] - half, ctr[0] + half)
    ylim = (ctr[1] - half, ctr[1] + half)

    # reserved bands (figure fraction): optional heading on top, per-panel caption lines
    # above each axes, tick labels + legend + axis note below. Nothing overlaps by design.
    top = 0.862 if a.title else 0.895
    fig_h = 5.9 if a.title else 5.55
    figsize = tuple(a.figsize) if a.figsize else (4.9 * len(runs), fig_h)
    fig, axes = plt.subplots(1, len(runs), figsize=figsize, dpi=170)
    axes = np.atleast_1d(axes)  # subplots(1, 1) returns a bare Axes, not an array
    if a.axes_rect:
        if len(runs) != 1:
            raise SystemExit("--axes-rect applies to single-panel figures only")
        axes[0].set_position(a.axes_rect)
    else:
        fig.subplots_adjust(left=0.038, right=0.995, top=top, bottom=0.185, wspace=0.10)
    if a.title:
        fig.text(0.038, a.title_y, a.title, ha="left", va="center",
                 fontsize=a.title_fontsize, fontweight="bold", color=DARK)

    rng = np.random.default_rng(42)
    for ax, panel in zip(axes, runs):
        if panel[0] == "empty":
            _, label, reward, note = panel
            P_full = tags = node2item = align = None
            parts = gold_parts
        else:
            _, label, P_full, tags, node2item, parts, align, reward = panel
        # z-order: unmapped geometry at the back (rollout2's floor blob must not bury items),
        # then the pale original underlay, then the bold reconstruction on top
        if tags is not None:
            un = np.isin(tags, [n for n, it in node2item.items() if it == "unmapped"])
            extra = ~np.isin(tags, list(node2item))  # nodes missing from item_map entirely
            for m in (un, extra):
                if m.any():
                    p = decim(P_full[m], rng)
                    ax.scatter(p[:, 0], p[:, 1], s=4.0, c=[UNMAPPED_PALE], alpha=0.8,
                               linewidths=0, rasterized=True)
        for name, gv in parts:  # original: large pale dots in a lighter tint of the item colour
            c = pale(item_colors.get(name, UNMAPPED_COLOR))
            g = decim(gv, rng)
            ax.scatter(g[:, 0], g[:, 1], s=4.0, c=[c], alpha=0.9, linewidths=0, rasterized=True)
        if tags is not None:
            for item in legend_order:  # reconstruction: small bold dots in the full item colour
                nodes = [n for n, it in node2item.items() if it == item]
                mask = np.isin(tags, nodes)
                if mask.any():
                    p = decim(P_full[mask], rng)
                    ax.scatter(p[:, 0], p[:, 1], s=1.8, c=[item_colors[item]], alpha=0.9,
                               linewidths=0, rasterized=True)
        else:  # no-output run: say so in the panel itself, over the pale answer key
            ax.text(0.5, 0.56, "NO RECONSTRUCTED SCENE PRODUCED", transform=ax.transAxes,
                    ha="center", va="center", fontsize=11, fontweight="bold", color="0.38")
            ax.text(0.5, 0.485, "no agent scene — no geometry to align or score",
                    transform=ax.transAxes, ha="center", va="center", fontsize=9, color="0.45")

        ax.set_xlim(*xlim); ax.set_ylim(*ylim)
        ax.set_aspect("equal")
        ax.xaxis.set_major_locator(plt.MultipleLocator(1))
        ax.yaxis.set_major_locator(plt.MultipleLocator(1))
        ax.grid(True, color="0.90", linewidth=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(labelsize=7, length=2, colors="0.40")
        for spine in ax.spines.values():
            spine.set_color("0.75"); spine.set_linewidth(0.8)

        # furniture labels near the original items (golden is identical in every panel)
        for name, gv in parts:
            c = tuple(0.72 * v for v in item_colors.get(name, UNMAPPED_COLOR))
            dx, dy = label_offsets.get(name, (0.0, 0.0))
            ax.text(float(np.mean(gv[:, 0])) + dx, float(np.mean(gv[:, 1])) + dy,
                    name.replace("_", " "), fontsize=8, fontweight="bold", color=c,
                    ha="center", va="center", zorder=10,
                    path_effects=[pe.withStroke(linewidth=2.4, foreground="white")])

        # two reserved caption lines above the panel, left-aligned like the example
        ax.text(0.0, 1.088, f"{label} — reward {reward:.3f}", transform=ax.transAxes,
                ha="left", va="bottom", fontsize=10.5, fontweight="bold", color=DARK)
        if align is not None:
            yaw_s = uminus(f"{align['yaw_deg']:+.1f}")
            tf = (f"×{align['scale']:.2f} scale · {yaw_s}° yaw · "
                  f"{align['tilt_deg']:.1f}° tilt")
            if "TMP_FLOOR" in tags:
                tf += " · extra floor shrank + rotated the fit"
        else:
            tf = note  # no-output panel: why there is no transform
        ax.text(0.0, 1.022, tf, transform=ax.transAxes,
                ha="left", va="bottom", fontsize=8.8, color=SUBDUED_RED)

    # compact bottom-left legend (reserved band below the axes)
    handles = ([Line2D([0], [0], marker="o", ls="", markersize=7, alpha=0.9,
                       color=pale((0.4, 0.4, 0.4)), label="pale = original"),
                Line2D([0], [0], marker="o", ls="", markersize=5, alpha=0.9, color="0.25",
                       label="bold = reconstruction (same item colour)")]
               + [Patch(color=item_colors[n], label=n.replace("_", " ")) for n in legend_order]
               + [Patch(facecolor=UNMAPPED_PALE, edgecolor=UNMAPPED_COLOR,
                        label="unmapped (model only)")])
    n_col = a.legend_ncol or len(handles)
    un_text = a.unmapped_note or (
        "grey = unmapped model geometry (rollout 2's extra 40×40 m floor plane) · "
        "dots are surface samples; colour is item identity, not measured error")
    ax_text = a.axis_note or (
        "X (m) → right when facing the bed from the foot · Y (m) → toward the head wall · "
        "grid lines 1 m apart · all panels share the same axes and equal x/y scale")
    if a.wrap_notes:
        # narrow figures: wrap the footnotes and stack them above the bottom edge,
        # legend rows above the notes — everything stays inside the canvas
        un_lines = (textwrap.wrap(un_text, a.wrap_notes, break_long_words=False,
                                  break_on_hyphens=False) if a.full_legend else [])
        ax_lines = textwrap.wrap(ax_text, a.wrap_notes, break_long_words=False,
                                 break_on_hyphens=False)
        line_h = 0.0185
        y = 0.016
        for ln in reversed(ax_lines):  # first wrapped line ends up on top
            fig.text(0.038, y, ln, ha="left", va="center", fontsize=8.2, color="0.35")
            y += line_h
        if un_lines:
            y += 0.006
            for ln in reversed(un_lines):
                fig.text(0.038, y, ln, ha="left", va="center", fontsize=8.2, color="0.35")
                y += line_h
        y += 0.008
        fig.legend(handles=handles, loc="lower left", ncol=n_col, fontsize=8.2,
                   frameon=False, bbox_to_anchor=(0.038, y), columnspacing=1.15,
                   handletextpad=0.55, borderaxespad=0.0)
    else:
        leg_y = 0.082 if a.full_legend else 0.068
        fig.legend(handles=handles, loc="lower left", ncol=n_col, fontsize=8.2,
                   frameon=False, bbox_to_anchor=(0.038, leg_y), columnspacing=1.15,
                   handletextpad=0.55, borderaxespad=0.0)
        note_y = 0.030
        if a.full_legend:
            fig.text(0.038, 0.062, un_text, ha="left", va="center", fontsize=8.2, color="0.35")
            note_y = 0.014
        fig.text(0.038, note_y, ax_text, ha="left", va="center", fontsize=8.2, color="0.35")

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    fig.savefig(a.out)
    print(f"wrote {a.out}")
    for panel in runs:
        if panel[0] == "empty":
            print(f"  {panel[1]}: reward {panel[2]:.10f} (no scene — nothing to reproduce)")
            continue
        _, label, _, _, _, _, align, reward = panel
        print(f"  {label}: reward {reward:.10f} (repro OK) · scale ×{align['scale']:.4f} · "
              f"yaw {align['yaw_deg']:+.2f}° · tilt {align['tilt_deg']:.2f}°")


if __name__ == "__main__":
    main()
