// Test browser wallet migration and corrupt stored profile without a browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('join.html', 'utf8');
const from = html.indexOf('function readSavedObject(key)');
const to = html.indexOf('let knownStamps = 0;', from);
assert.ok(from > 0 && to > from, 'Wallet bootstrap script expected');
const bootstrap = html.slice(from, to);
const storage = new Map();
const sandbox = {
  bizId: 29,
  localStorage: {
    getItem: key => storage.has(key) ? storage.get(key) : null,
    setItem: (key, value) => storage.set(key, String(value))
  },
  crypto: { randomUUID: () => 'e7f01d1a-3f19-4bea-bfee-987e178dc383' },
};
function run() {
  const ctx = vm.createContext(sandbox);
  vm.runInContext(bootstrap + ';globalThis.result={wallet:globalWalletUuid,profile:savedProfile};', ctx);
  return ctx.result;
}
storage.set('loial_universal_profile','{invalid-json');
storage.set('loial_card_29','{invalid-json');
let a=run();
assert.equal(a.profile, null);
assert.equal(a.wallet, 'W-e7f01d1a-3f19-4bea-bfee-987e178dc383');
assert.equal(storage.get('loial_universal_profile'), '{invalid-json', 'Do not erase corrupted data');

storage.delete('loial_universal_uuid');
storage.set('loial_card_29',JSON.stringify({uuid:'legacy-wallet-12345678'}));
storage.set('loial_universal_profile',JSON.stringify({name:'Test User'}));
a=run();
assert.equal(a.wallet, 'legacy-wallet-12345678');
assert.equal(a.profile.name, 'Test User');

storage.delete('loial_universal_uuid');
storage.set('loial_card_29',JSON.stringify({uuid:'bad uuid with spaces'}));
a=run();
assert.equal(a.wallet, 'W-e7f01d1a-3f19-4bea-bfee-987e178dc383');
assert.match(bootstrap, /readSavedObject\('loial_universal_profile'\)/);
console.log('PASS: corrupt storage, valid legacy wallet and invalid legacy ID');
