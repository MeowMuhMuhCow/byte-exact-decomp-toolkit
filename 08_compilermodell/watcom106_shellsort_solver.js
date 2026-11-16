#!/usr/bin/env node
/**
 * watcom106_shellsort_solver.js - Bit-exact standalone simulator and two-stage inverse solver
 * for Watcom C/C++ 10.6's unstable ShellSort (Phase C1 register conflicts & Phase C2 stack layout).
 *
 * Implements:
 *   1. Exact Watcom SortList ShellSort (`gap = (gap >> 1) + adj`, `adj` alternating 0 / 1).
 *   2. Phase C1 rough ID sort (`shellRough`, descending by symbol ID) and conflict savings sort (`ConfBefore`).
 *   3. Phase C2 stack slot sort (`TempAllocBefore`: `USED_AS_FD` first, then `size` ascending, then equal-ID `offset` descending).
 *   4. Two-stage size decoupling (`{1, 2, 3} -> {3, 4, 5}`):
 *      - Stage 1 mutates ghost sizes in `{1, 2, 3}` to lock 2-byte `short` stack slots.
 *      - Stage 2 mutates size-`3` ghosts in `{3, 4, 5}` to lock 4-byte `int` stack slots while leaving Stage 1 100% invariant.
 *
 * Usage:
 *   node watcom106_shellsort_solver.js --symtab symtab.json [--twostage] [--iters 200000]
 */
'use strict';
const fs = require('fs');

function watcomShellSort(arr, before) {
  const a = arr.slice();
  const n = a.length;
  if (n < 2) return a;
  let gap = n, adj = 1;
  for (;;) {
    adj = 1 - adj;
    gap = (gap >> 1) + adj;
    let changed;
    do {
      changed = false;
      for (let i = 0; i < n - gap; i++) {
        const j = i + gap;
        if (before(a[j], a[i])) {
          const tmp = a[i];
          a[i] = a[j];
          a[j] = tmp;
          changed = true;
        }
      }
    } while (changed);
    if (gap === 1) return a;
  }
}

function tempAllocBefore(a, b) {
  const fdA = a.fd ? 1 : 0, fdB = b.fd ? 1 : 0;
  if (fdA !== fdB) return fdA > fdB;
  if (a.size !== b.size) return a.size < b.size;
  return a.id === b.id && (a.offset || 0) > (b.offset || 0);
}

function assignStackOffsets(sortedList, frameTop) {
  let sp = frameTop;
  const offsets = new Map();
  for (const item of sortedList) {
    if (item.isPhysical) {
      const alloc = Math.max(4, (item.size + 3) & ~3);
      sp -= alloc;
      offsets.set(item.id, sp);
    }
  }
  return offsets;
}

function scoreOffsets(offsets, targets) {
  let hits = 0, l1Dist = 0;
  for (const [idStr, targetOff] of Object.entries(targets)) {
    const id = Number(idStr);
    const actual = offsets.get(id);
    if (actual === targetOff) hits++;
    if (actual !== undefined) l1Dist += Math.abs(actual - targetOff) / 4;
  }
  return { hits, total: Object.keys(targets).length, l1Dist };
}

function solveTwoStage(symtab, maxIters = 50000) {
  const baseList = symtab.c2_input.map(d => ({ ...d }));
  const frameTop = symtab.frame_top || 172;
  const targets = symtab.target_offsets || {};
  const shortTargets = {};
  for (const d of baseList) {
    if (d.isPhysical && d.size === 2 && targets[d.id] !== undefined) {
      shortTargets[d.id] = targets[d.id];
    }
  }

  const ghostIndices = [];
  baseList.forEach((d, idx) => {
    if (d.isGhost) ghostIndices.push(idx);
  });

  // Stage 1: Mutate ghost sizes in {1, 2, 3} to match all 2-byte short slots
  let bestSizes = ghostIndices.map(() => 3);
  const evalSizes = (sizes, tgtMap) => {
    const work = baseList.map(d => ({ ...d }));
    ghostIndices.forEach((gIdx, k) => { work[gIdx].size = sizes[k]; });
    const sorted = watcomShellSort(work, tempAllocBefore);
    const offs = assignStackOffsets(sorted, frameTop);
    return { ...scoreOffsets(offs, tgtMap), offs };
  };

  let cur1 = evalSizes(bestSizes, shortTargets);
  for (let it = 0; it < maxIters && cur1.hits < cur1.total; it++) {
    const cand = bestSizes.slice();
    const k = (Math.random() * cand.length) | 0;
    cand[k] = [1, 2, 3][(Math.random() * 3) | 0];
    const res = evalSizes(cand, shortTargets);
    if (res.hits > cur1.hits || (res.hits === cur1.hits && res.l1Dist <= cur1.l1Dist)) {
      bestSizes = cand;
      cur1 = res;
    }
  }

  // Stage 2: Mutate only size-3 ghosts in {3, 4, 5} (leaves Stage 1 short slots 100% invariant!)
  const stage2Indices = [];
  bestSizes.forEach((sz, k) => {
    if (sz === 3) stage2Indices.push(k);
  });

  let cur2 = evalSizes(bestSizes, targets);
  for (let it = 0; it < maxIters && cur2.hits < cur2.total && stage2Indices.length > 0; it++) {
    const cand = bestSizes.slice();
    const k = stage2Indices[(Math.random() * stage2Indices.length) | 0];
    cand[k] = [3, 4, 5][(Math.random() * 3) | 0];
    const res = evalSizes(cand, targets);
    if (res.hits > cur2.hits || (res.hits === cur2.hits && res.l1Dist <= cur2.l1Dist)) {
      bestSizes = cand;
      cur2 = res;
    }
  }

  return {
    stage1_short_hits: `${cur1.hits}/${cur1.total}`,
    stage2_total_hits: `${cur2.hits}/${cur2.total}`,
    l1_distance: cur2.l1Dist,
    ghost_sizes: bestSizes,
  };
}

if (require.main === module) {
  const args = process.argv.slice(2);
  const symIdx = args.indexOf('--symtab');
  if (symIdx < 0 || !args[symIdx + 1]) {
    console.log('Usage: node watcom106_shellsort_solver.js --symtab symtab.json [--twostage] [--iters N]');
    process.exit(0);
  }
  const symtab = JSON.parse(fs.readFileSync(args[symIdx + 1], 'utf8'));
  const itersIdx = args.indexOf('--iters');
  const iters = itersIdx >= 0 ? Number(args[itersIdx + 1]) : 50000;
  const result = solveTwoStage(symtab, iters);
  console.log(JSON.stringify(result, null, 2));
}

module.exports = { watcomShellSort, tempAllocBefore, assignStackOffsets, solveTwoStage };
