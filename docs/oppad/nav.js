/* Op pad! — pure navigation logic: route parsing, snapping, turn state.
   No DOM, no network. Plain globals in the browser, CommonJS in node. */
(function (root) {
  'use strict';

  const R_EARTH = 6371000;
  const rad = d => d * Math.PI / 180;

  // Valhalla maneuver types that the copilot announces. Slight bends,
  // "continue", "becomes" and "stay" are skipped: the child sees "Rechtdoor!".
  const TURN_RIGHT = new Set([10, 11, 18, 20]);   // right, sharp right, ramp/exit right
  const TURN_LEFT = new Set([15, 14, 19, 21]);    // left, sharp left, ramp/exit left
  const ROUNDABOUT_ENTER = 26;
  const ROUNDABOUT_EXIT = 27;
  // Below this net heading change a roundabout counts as straight on.
  const ROUNDABOUT_STRAIGHT_DEG = 35;

  function decodePolyline(str, precision = 6) {
    const factor = Math.pow(10, precision);
    const pts = [];
    let index = 0, lat = 0, lon = 0;
    while (index < str.length) {
      for (const which of [0, 1]) {
        let result = 0, shift = 0, b;
        do {
          b = str.charCodeAt(index++) - 63;
          result |= (b & 0x1f) << shift;
          shift += 5;
        } while (b >= 0x20);
        const delta = (result & 1) ? ~(result >> 1) : (result >> 1);
        if (which === 0) lat += delta; else lon += delta;
      }
      pts.push([lat / factor, lon / factor]);
    }
    return pts;
  }

  function haversine(a, b) {
    const dLat = rad(b[0] - a[0]), dLon = rad(b[1] - a[1]);
    const h = Math.sin(dLat / 2) ** 2 +
      Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(dLon / 2) ** 2;
    return 2 * R_EARTH * Math.asin(Math.sqrt(h));
  }

  function bearing(a, b) {
    const y = Math.sin(rad(b[1] - a[1])) * Math.cos(rad(b[0]));
    const x = Math.cos(rad(a[0])) * Math.sin(rad(b[0])) -
      Math.sin(rad(a[0])) * Math.cos(rad(b[0])) * Math.cos(rad(b[1] - a[1]));
    return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
  }

  // Signed heading change from h1 to h2 in (-180, 180]; positive = right.
  function turnAngle(h1, h2) {
    let d = (h2 - h1 + 540) % 360 - 180;
    if (d === -180) d = 180;
    return d;
  }

  // Heading of the route around shape index i, measured over ~20 m so a
  // single GPS-noisy vertex doesn't decide the direction.
  function headingAt(pts, i, dir) {
    let j = i, dist = 0;
    while (dist < 20) {
      const k = j + dir;
      if (k < 0 || k >= pts.length) break;
      dist += haversine(pts[j], pts[k]);
      j = k;
    }
    if (j === i) return null;
    return dir > 0 ? bearing(pts[i], pts[j]) : bearing(pts[j], pts[i]);
  }

  function cumulative(pts) {
    const cum = [0];
    for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + haversine(pts[i - 1], pts[i]));
    return cum;
  }

  // Turn a Valhalla /route response into {pts, cum, length, time, turns[]}.
  // Each turn: {at (m along route), side 'left'|'right', street}.
  function parseValhalla(resp) {
    const leg = resp && resp.trip && resp.trip.legs && resp.trip.legs[0];
    if (!leg) throw new Error('geen route');
    const pts = decodePolyline(leg.shape, 6);
    const cum = cumulative(pts);
    const mans = leg.maneuvers || [];
    const turns = [];
    for (let m = 0; m < mans.length; m++) {
      const man = mans[m];
      const idx = man.begin_shape_index;
      let side = null;
      // A maneuver's street_names name the street you turn onto.
      let names = man.street_names || [];
      if (TURN_RIGHT.has(man.type)) side = 'right';
      else if (TURN_LEFT.has(man.type)) side = 'left';
      else if (man.type === ROUNDABOUT_ENTER) {
        // Same model as any turn: the net direction from entering to leaving.
        const exit = mans.slice(m + 1).find(x => x.type === ROUNDABOUT_EXIT);
        const hIn = headingAt(pts, idx, -1);
        const hOut = exit ? headingAt(pts, exit.begin_shape_index, +1) : null;
        if (exit && exit.street_names) names = exit.street_names;
        if (hIn != null && hOut != null) {
          const a = turnAngle(hIn, hOut);
          if (Math.abs(a) >= ROUNDABOUT_STRAIGHT_DEG && Math.abs(a) <= 170) {
            side = a > 0 ? 'right' : 'left';
          }
        }
      }
      if (!side) continue;
      turns.push({ at: cum[Math.min(idx, cum.length - 1)], side, street: names[0] || '' });
    }
    const summary = resp.trip.summary || {};
    return {
      pts, cum, turns,
      length: cum[cum.length - 1],
      time: summary.time || leg.summary && leg.summary.time || null,
    };
  }

  // Project point p onto the route. Local equirectangular projection is
  // plenty at bike scale. Searches forward from the last known segment first
  // so a route that doubles back doesn't snap to the wrong pass.
  function snap(route, p, hintSeg = 0) {
    const { pts, cum } = route;
    const kx = Math.cos(rad(p[0])) * R_EARTH * Math.PI / 180;
    const ky = R_EARTH * Math.PI / 180;
    const best = { dist: Infinity, along: 0, seg: 0 };
    const scan = (from, to) => {
      for (let i = from; i < to; i++) {
        const ax = (pts[i][1] - p[1]) * kx, ay = (pts[i][0] - p[0]) * ky;
        const bx = (pts[i + 1][1] - p[1]) * kx, by = (pts[i + 1][0] - p[0]) * ky;
        const dx = bx - ax, dy = by - ay;
        const len2 = dx * dx + dy * dy;
        let t = len2 > 0 ? -(ax * dx + ay * dy) / len2 : 0;
        t = Math.max(0, Math.min(1, t));
        const cx = ax + t * dx, cy = ay + t * dy;
        const d = Math.sqrt(cx * cx + cy * cy);
        if (d < best.dist) {
          best.dist = d;
          best.seg = i;
          best.along = cum[i] + t * (cum[i + 1] - cum[i]);
        }
      }
    };
    const n = pts.length - 1;
    const lo = Math.max(0, hintSeg - 3);
    // Window ahead of the hint: ~150 vertices covers well over a kilometre.
    scan(lo, Math.min(n, hintSeg + 150));
    if (best.dist > 40) scan(0, n);          // lost: search the whole route
    return best;
  }

  // Point at distance `along` metres on the route (used by the test feed).
  function pointAt(route, along) {
    const { pts, cum } = route;
    if (along <= 0) return pts[0];
    for (let i = 1; i < pts.length; i++) {
      if (cum[i] >= along) {
        const seg = cum[i] - cum[i - 1];
        const t = seg > 0 ? (along - cum[i - 1]) / seg : 0;
        return [pts[i - 1][0] + t * (pts[i][0] - pts[i - 1][0]),
                pts[i - 1][1] + t * (pts[i][1] - pts[i - 1][1])];
      }
    }
    return pts[pts.length - 1];
  }

  const DEFAULTS = {
    readyM: 100,       // "Arm klaar" from this many metres before a turn
    nowM: 15,          // "NU!" from this many metres ...
    nowS: 4,           // ... or this many seconds at current speed, whichever first
    arriveM: 20,
    offRouteM: 30,
    offRouteS: 6,
    passedM: 8,        // turn counts as taken this far past its point
  };

  // The ride state machine. Feed it fixes; it returns what to show.
  class Ride {
    constructor(route, opts = {}) {
      this.opts = Object.assign({}, DEFAULTS, opts);
      this.stars = 0;
      this.arrived = false;
      this.setRoute(route);
    }

    setRoute(route) {
      this.route = route;
      this.seg = 0;
      this.along = 0;
      this.nextTurn = 0;
      this.offSince = null;
      this.lastFix = null;
      this.speed = 0;
    }

    // fix: {lat, lon, t (ms), speed (m/s or null)}
    update(fix) {
      const o = this.opts;
      const s = snap(this.route, [fix.lat, fix.lon], this.seg);
      let along = s.along;
      // Never run backwards along the route on GPS jitter.
      if (along < this.along && this.along - along < 25) along = this.along;

      // Speed: device value when it has one, otherwise from progress.
      let v = fix.speed;
      if ((v == null || isNaN(v) || v < 0) && this.lastFix) {
        const dt = (fix.t - this.lastFix.t) / 1000;
        if (dt > 0) v = Math.max(0, (along - this.along) / dt);
      }
      if (v != null && !isNaN(v)) this.speed = this.speed ? 0.6 * this.speed + 0.4 * v : v;

      const onRoute = s.dist <= o.offRouteM;
      if (onRoute) {
        this.offSince = null;
        this.seg = s.seg;
        this.along = along;
      } else if (this.offSince == null) {
        this.offSince = fix.t;
      }
      this.lastFix = fix;

      const turns = this.route.turns;
      while (this.nextTurn < turns.length && this.along > turns[this.nextTurn].at + o.passedM) {
        this.nextTurn++;
        this.stars++;
      }
      const remaining = Math.max(0, this.route.length - this.along);
      if (onRoute && remaining <= o.arriveM) this.arrived = true;

      const reroute = this.offSince != null && (fix.t - this.offSince) / 1000 >= o.offRouteS;
      const turn = turns[this.nextTurn] || null;
      const toTurn = turn ? turn.at - this.along : null;
      let screen = 'cruise';
      if (this.arrived) screen = 'arrived';
      else if (onRoute && turn) {
        const nowAt = Math.max(o.nowM, this.speed * o.nowS);
        if (toTurn <= nowAt) screen = 'now';
        else if (toTurn <= o.readyM) screen = 'ready';
      }
      return {
        screen, reroute, onRoute,
        side: turn ? turn.side : null,
        street: turn ? turn.street : '',
        toTurn, remaining, speed: this.speed, stars: this.stars,
      };
    }
  }

  const api = { decodePolyline, haversine, bearing, turnAngle, parseValhalla, snap, pointAt, Ride, DEFAULTS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.OpPadNav = api;
})(this);
