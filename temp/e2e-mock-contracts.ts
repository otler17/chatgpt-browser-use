import type { Page } from '@playwright/test';
import { RUNTIME_FIELD_NAMES, RUNTIME_SCHEMA_DIGEST, RUNTIME_SCHEMA_ID, RUNTIME_SCHEMA_VERSION } from '../../contracts/runtime-field-names.generated';

const fields = RUNTIME_FIELD_NAMES.map((name) => ({
  name,
  type: 'str',
  has_default: true,
  default: '',
  runtime_choices: null,
  ui_choices: null,
  ui_hidden_reason: null,
  path_kind: null,
  path_picker: null,
  path_direction: null,
  artifact_category: null,
  path_note: null,
}));

const schema = {
  schema_id: RUNTIME_SCHEMA_ID,
  schema_version: RUNTIME_SCHEMA_VERSION,
  source: 'playwright-synthetic-runtime-contract',
  source_sha256: 'e2e-runtime-source',
  field_count: fields.length,
  fields,
  runtime_choices: {},
  generator_ui_choices: {},
  ui_hidden_reasons: {},
  path_fields: {},
};

const manifestFields = RUNTIME_FIELD_NAMES.map((name, index) => ({
  name,
  label: name,
  help: 'Synthetic browser-verification field.',
  disposition: 'direct',
  control: 'text',
  route: '/overview',
  area: 'Verification',
  page: 'Overview',
  section: 'verification-runtime-fields',
  section_label: 'Runtime fields',
  section_description: 'Synthetic exhaustive field surface for browser verification.',
  order: index,
  presentation: 'guided',
  unit: null,
  evidence_role: 'verification',
  capability: null,
  capabilities: [],
  availability: null,
  path: null,
  search: [name],
  legacy: {},
}));

const manifest = {
  schema: 'astral.scenario_studio.field_manifest/v2',
  version: 2,
  runtime_schema_id: RUNTIME_SCHEMA_ID,
  runtime_schema_version: RUNTIME_SCHEMA_VERSION,
  runtime_field_count: RUNTIME_FIELD_NAMES.length,
  editor_extension_field_count: 0,
  fields: manifestFields,
  editor_extensions: [],
  sections: [{
    id: 'verification-runtime-fields',
    route: '/overview',
    area: 'Verification',
    page: 'Overview',
    label: 'Runtime fields',
    description: 'Synthetic exhaustive field surface for browser verification.',
    order: 0,
  }],
  dependency_model: {
    schema: 'astral.scenario_studio.field_dependencies/v1',
    field_rules: {},
    editor_rules: {},
    collection_rules: {},
    row_group_rules: {},
    parent_policies: {},
  },
};

const capabilities = { schema: 'astral.capability_registry/v1', capabilities: [] };
const health = {
  ok: true,
  service: 'astral-scenario-studio',
  version: 2,
  features: ['contracts', 'materialization'],
  request_token: 'e2e-token',
  project_root: '/tmp/e2e-project',
  asset_roots: ['/tmp/e2e-project'],
  algorithm_catalog_path: '/tmp/e2e-project/algorithms.json',
  artifact_explorer_url: 'http://127.0.0.1:8095',
  algorithm_studio_url: 'http://127.0.0.1:8085',
};

export async function installContractMocks(page: Page): Promise<void> {
  await page.route('**/api/health', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json; charset=utf-8', body: JSON.stringify(health) });
  });
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
    await route.fulfill({ status: 200, contentType: 'application/json; charset=utf-8', headers: { 'X-Astral-Contract-Digest': 'e2e-capabilities' }, body: JSON.stringify(capabilities) });
  });
  await page.route('**/api/contracts/studio-manifest', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json; charset=utf-8', headers: { 'X-Astral-Contract-Digest': 'e2e-studio-manifest' }, body: JSON.stringify(manifest) });
  });
  await page.route('**/api/adcs/algorithm-catalog', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json; charset=utf-8', body: JSON.stringify({ schema: 'astral.scenario_studio.algorithm_catalog/v1', entries: [] }) });
  });
}
