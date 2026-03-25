# Volume at Price — Dynamic Bins Design

**Date:** 2026-03-25
**Status:** Approved

## Problem

The current Volume at Price (VAP) sidebar uses a hardcoded `VAP_BINS = 40` constant, producing a sparse, low-resolution histogram on the 1-year daily chart (~252 candles). Visual resolution does not adapt to the chart's rendered height.

## Goal

Increase VAP visual resolution by making the bin count dynamic — scaling to fill the chart's rendered height automatically.

## Approach

ResizeObserver on the VAP container div. Bin count is computed at runtime from measured height.

## Design

### Constants

Remove `VAP_BINS = 40`. Update constants:
- `BAR_HEIGHT = 2` (px) — deliberately reduced from 4px; smaller bars are required to achieve meaningful resolution with dynamic bin counts
- `BAR_GAP = 1` (px)

Slot size = 3px per bin.

### `computeVAP(data, bins)` (component-private)

Add `bins` as an explicit parameter replacing the removed `VAP_BINS` constant. This function has one callsite (`VolumeAtPrice`) and is not exported. All internal logic unchanged — bucketing by close price, volume accumulation, max volume, price level midpoints.

### `VolumeAtPrice` component

1. Add `containerHeight` state, initialised to `0`.
2. Attach `useRef` to the container div.
3. `useEffect` sets up a `ResizeObserver` on the ref. On measurement callback, set `containerHeight` from `entry.contentRect.height`. The effect **must return a cleanup function** that calls `observer.disconnect()` to avoid callbacks firing on an unmounted component.
4. If `containerHeight === 0`, render the container div (preserving its `position: absolute` + `top/bottom/right` styles so the ResizeObserver gets a non-zero measurement on first callback) but render no bars — skip the `computeVAP` call entirely in this case.
5. Otherwise derive bin count: `Math.max(10, Math.floor(containerHeight / 3))` and pass into `computeVAP`.

### Render loop

- `height: BAR_HEIGHT` (2px) on each bar div.
- Remove `justifyContent: "space-between"` from the flex container — bars stack top-to-bottom.
- Add `gap: 1` on the flex container (not `marginBottom` on individual bars — `gap` does not apply after the last item, keeping total height consistent with the measured container).
- Color logic, tooltip (`title`), and right-to-left bar growth unchanged.

## Expected Result

On a ~300px chart: ~100 bins (vs. 40 previously).
Adapts automatically on window resize or if chart height changes.
