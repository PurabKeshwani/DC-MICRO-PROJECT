# Design

## Direction
A student explains a protocol on a laptop in a bright classroom, so a light teaching workspace keeps explanatory text and projected diagrams readable. The approved plan puts topology beside live commentary. A restrained framed sheet provides quiet surfaces; message colours carry meaning.

## Layout
Single screen, no sidebar. Compact header and control strip, then a two-column teaching workspace (network and commentary), compact local process cards, and observer/history panels below. At 1366px: 24px outer gutters, 16px gaps, 1318px content. The primary workspace is approximately 58% diagram / 42% commentary. No mobile-specific work.

## Colour and type
Cool light neutral background, light panel surface, dark ink, blue control accent. Amber REQUEST, blue REPLY, green RELEASE and CS with explicit labels. Red is reserved for errors. CSS custom properties own the colours. IBM Plex Sans with Segoe UI/system fallbacks for text, Consolas/system monospace for clocks and tuples. Body 15-16px, supporting labels at least 12px, diagram labels at least 12px.

## Components and motion
Flat 1px panel borders, 10px corners, no glow or gradient text. Stable process DOM nodes and SVG nodes; animate only the last delivered packet for a short explanatory motion. Pause freezes playback. Respect reduced motion. Logs filter independently of the current commentary. Observer rows distinguish active requests from pending RELEASE cleanup.

## Scope
User approved implementation after research and live audit, with laptop-only scope and minimal complexity. Keep Flask, plain JavaScript and SVG. The existing local-state algorithm remains intact. Image probes are skipped because this is a concrete repair of the inspected interface with an approved direction, and no bitmap assets are needed.

## Algorithm selector
One dropdown in the existing toolbar selects Lamport or Ricart–Agrawala. Switching pauses and resets the run, preserving process count, delay, and CS duration. Reuse every existing panel. In Ricart–Agrawala, process cards show deferred replies, the inspector requires all peer replies, RELEASE controls are hidden, the final phase reads Reply on exit, and the reference uses 2(N−1) messages. No new navigation, modes, or dependencies.
