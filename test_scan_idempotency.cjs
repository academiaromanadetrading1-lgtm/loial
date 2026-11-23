// Browser-independent regression tests for scan idempotency behavior.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('scan.html', 'utf8');
const start = source.indexOf('function stableScanOperation(walletUuid)');
const end = source.indexOf('async function grantStampDirect(walletUuid)', start);
assert.ok(start >= 0 && end > start, 'Scan operation functions must exist');
const functions = source.slice(start, end);
const saved = new Map();
let nextId = 0;
const context = {
  bizId: '37',
  sessionStorage: {
    getItem: (key) => saved.has(key) ? saved.get(key) : null,
    setItem: (key, value) => saved.set(key, value),
    removeItem: (key) => saved.delete(key),
  },
  crypto: { randomUUID: () => 'operation-' + (++nextId) },
  Date,
  JSON,
};
vm.createContext(context);
vm.runInContext(functions, context);

const first = vm.runInContext('stableScanOperation("wallet-A")', context);
const retry = vm.runInContext('stableScanOperation("wallet-A")', context);
assert.equal(first, retry, 'Network retry must reuse its idempotency key');
assert.equal(nextId, 1);

vm.runInContext('clearConfirmedScanOperation("wallet-A")', context);
const secondPurchase = vm.runInContext('stableScanOperation("wallet-A")', context);
assert.notEqual(first, secondPurchase, 'Confirmed purchase must allow a fresh idempotency key');
assert.equal(nextId, 2);

const otherWallet = vm.runInContext('stableScanOperation("wallet-B")', context);
assert.notEqual(otherWallet, secondPurchase, 'Different customers use different operations');
assert.ok(saved.has('loial_pending_scan_37_wallet-B'));

assert.match(source, /if\s*\(data\.duplicate_ignored\)\s*\{\s*clearConfirmedScanOperation\(walletUuid\)/);
assert.match(source, /clearConfirmedScanOperation\(walletUuid\);\s*playBeep\(\)/);
assert.ok(!source.slice(source.indexOf('if (!res.ok)'), source.indexOf('if(data.duplicate_ignored)')).includes('clearConfirmedScanOperation'),
  'Do not clear operation key on HTTP errors');

console.log('PASS: retry/replay/new purchase and customer isolation');
