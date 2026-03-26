const test = require("node:test");
const assert = require("node:assert/strict");

const tooltip = require("../tooltip.js");

test("createRelativeAnchor stores pointer offset within the cell bounds", () => {
  const anchor = tooltip.createRelativeAnchor(
    { left: 100, top: 50, width: 80, height: 40 },
    130,
    70
  );

  assert.deepEqual(anchor, { relativeX: 30, relativeY: 20 });
});

test("resolveAnchorPoint falls back to the cell bottom-left when no pointer anchor exists", () => {
  const point = tooltip.resolveAnchorPoint(
    { left: 24, top: 18, width: 100, height: 36, bottom: 54 },
    null
  );

  assert.deepEqual(point, { x: 24, y: 54 });
});

test("computeTooltipPosition flips above and left when the anchor is near viewport edges", () => {
  const position = tooltip.computeTooltipPosition({
    anchorX: 310,
    anchorY: 230,
    tooltipWidth: 120,
    tooltipHeight: 90,
    viewportWidth: 360,
    viewportHeight: 260,
    viewportPadding: 16,
    offset: 8,
  });

  assert.deepEqual(position, { left: 182, top: 132 });
});

test("computeTooltipPosition keeps the tooltip inside viewport padding when space is tight", () => {
  const position = tooltip.computeTooltipPosition({
    anchorX: 10,
    anchorY: 10,
    tooltipWidth: 140,
    tooltipHeight: 120,
    viewportWidth: 160,
    viewportHeight: 150,
    viewportPadding: 12,
    offset: 8,
  });

  assert.deepEqual(position, { left: 12, top: 18 });
});
