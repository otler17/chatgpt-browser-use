import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import type { Page } from '@playwright/test';

const readJson = (relative: string) => JSON.parse(readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf-8'));
const capabilities = readJson('../../contracts/capability_registry.snapshot.json');
const manifest = readJson('../../studio-manifest/studio_field_manifest.json');

const RUNTIME_SCHEMA_DIGEST = 'bec8d70b59fff2b311fb8ed71a261ad70af46352cfaf29898dae0d6e1d1662af';

function mockRuntimeType(control: string): { type: string; value: unknown } {
  if (control === 'toggle') return { type: 'bool', value: false };
  if (control === 'number') return { type: 'float', value: 0 };
  if (['vector', 'matrix', 'color-rgba', 'path-list'].includes(control)) return { type: 'tuple', value: [] };
  if (control === 'entity-collection') return { type: 'list', value: [] };
  if (control === 'json') return { type: 'tuple', value: [] };
  return { type: 'str', value: '' };
}

const fields = manifest.fields.map((entry: { name: string; control: string }) => {
  const mock = mockRuntimeType(entry.control);
  return {
    name: entry.name,
    type: mock.type,
    has_default: true,
    default: mock.value,
    runtime_choices: null,
    ui_choices: null,
    ui_hidden_reason: null,
    path_kind: null,
    path_picker: null,
    path_direction: null,
    artifact_category: null,
    path_note: null,
  };
});
const schema = {
  schema_id: 'adcs-hil.scenario_config.v1',
  schema_version: 1,
  source: 'playwright-synthetic-runtime-contract',
  source_sha256: 'e2e-runtime-source',
  field_count: fields.length,
  fields,
  runtime_choices: {},
  generator_ui_choices: {},
  ui_hidden_reasons: {},
  path_fields: {},
};

export async function installContractMocks(page: Page): Promise<void> {
  await page.route('**/api/contracts/scenario-schema', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json; charset=utf-8',
      headers: {
        'X-Astral-Contract-Digest': RUNTIME_SCHEMA_DIGEST,
        'X-Astral-Runtime-Contract-Current': 'true',
        'X-Astral-Runtime-Source-SHA256': schema.source_sha256,
      },
      body: JSON.stringify(schema),
    });
  });
  await page.route('**/api/contracts/capabilities', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json; charset=utf-8',
      headers: { 'X-Astral-Contract-Digest': 'e2e-capabilities' },
      body: JSON.stringify(capabilities),
    });
  });
  await page.route('**/api/contracts/studio-manifest', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json; charset=utf-8',
      headers: { 'X-Astral-Contract-Digest': 'e2e-studio-manifest' },
      body: JSON.stringify(manifest),
    });
  });
  await page.route('**/api/algorithms/catalog', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json; charset=utf-8',
      body: JSON.stringify({ schema: 'astral.algorithm_registry_export/v1', algorithms: [] }),
    });
  });
}
