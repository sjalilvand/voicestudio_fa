/**
 * macOS window chrome, defined once for the main process (where the traffic
 * lights are placed) and the renderer (which must keep content out from under
 * them). These used to be two unrelated magic numbers, `trafficLightPosition`
 * in main and a hand-tuned row height in the sidebar, so every OS or layout
 * change re-broke the overlap.
 */

/** Top-left of the traffic-light cluster, in window points. */
export const MAC_TRAFFIC_LIGHTS = { x: 16, y: 18 } as const;

/**
 * Tallest the cluster gets: the classic buttons are 12-14px, macOS 26+ draws
 * larger ones with a halo. Sized for the larger so nothing overlaps on either.
 */
export const MAC_TRAFFIC_LIGHTS_HEIGHT = 22;

/** Breathing room kept between the lights and the first content below them. */
export const MAC_TRAFFIC_LIGHTS_GAP = 8;

/**
 * Height of the strip that belongs to the traffic lights. Sidebar content
 * starts below it, in its own row, instead of sharing vertical space with the
 * lights.
 */
export const MAC_TRAFFIC_LIGHTS_BAND =
  MAC_TRAFFIC_LIGHTS.y + MAC_TRAFFIC_LIGHTS_HEIGHT + MAC_TRAFFIC_LIGHTS_GAP;
