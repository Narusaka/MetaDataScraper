import assert from 'node:assert/strict';
import test from 'node:test';

import { getConnectivityTone, isConnectivityUsable } from './connectivityStatus.ts';

test('connectivity status maps skipped configuration to warning but still usable', () => {
  assert.equal(getConnectivityTone({ status: 'ok' }), 'success');
  assert.equal(getConnectivityTone({ status: 'skipped' }), 'warning');
  assert.equal(getConnectivityTone({ status: 'failed' }), 'danger');
  assert.equal(getConnectivityTone(undefined), 'danger');

  assert.equal(isConnectivityUsable({ status: 'ok' }), true);
  assert.equal(isConnectivityUsable({ status: 'skipped' }), true);
  assert.equal(isConnectivityUsable({ status: 'failed' }), false);
});
