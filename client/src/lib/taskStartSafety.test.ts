import assert from 'node:assert/strict';
import test from 'node:test';

import {
  validateStartSafetyConfig,
} from './taskStartSafety.ts';

test('validateStartSafetyConfig rejects missing and unsafe copy paths', () => {
  assert.equal(validateStartSafetyConfig({ strategy: 'audit', inputPath: '' }), 'Target path is required');
  assert.equal(
    validateStartSafetyConfig({ strategy: 'copy', inputPath: '/media', outputPath: '' }),
    'Output path is required for copy mode',
  );
  assert.equal(
    validateStartSafetyConfig({ strategy: 'copy', inputPath: '/media', outputPath: '/media' }),
    'Output path must be different from target path',
  );
  assert.equal(validateStartSafetyConfig({ strategy: 'copy', inputPath: '/media', outputPath: '/library' }), null);
  assert.equal(
    validateStartSafetyConfig({ strategy: 'audit', inputPath: '/media', operationScope: 'organize_only' }),
    'Files-only scope requires Organize or Copy as the plan target',
  );
  assert.equal(
    validateStartSafetyConfig({ strategy: 'organize', inputPath: '/media', operationScope: 'nfo_only' }),
    'NFO-only and artwork-only scopes use the Metadata plan target',
  );
});
