import { expect, test } from '@playwright/test';
import { installContractMocks } from './mock-contracts';

const routes = [
  '/overview',
  '/mission/intent-run',
  '/spacecraft/vehicle-geometry',
  '/spacecraft/reaction-wheels',
  '/gnc/guidance',
  '/gnc/algorithms',
  '/integration/hil',
  '/visualization',
  '/verify-export',
  '/runtime-inspector',
];

test.beforeEach(async ({ page }) => {
  await installContractMocks(page);
});

test('boots into the Carbon shell with one runtime authority', async ({ page }) => {
  await page.goto('/studio/');
  await expect(page.getByRole('heading', { name: 'Scenario Studio' })).toBeVisible();
  await expect(page.getByText('742 runtime fields')).toBeVisible();
  await expect(page.locator('[data-field]').first()).toBeVisible();
});

test('all primary destinations are reachable and nonblank', async ({ page }) => {
  for (const route of routes) {
    await page.goto(`/studio/#${route}`);
    await expect(page.locator('main')).toBeVisible();
    await expect(page.locator('main')).not.toBeEmpty();
  }
});

test('keyboard focus reaches semantic navigation', async ({ page }) => {
  await page.goto('/studio/');
  for (let i = 0; i < 20; i += 1) {
    await page.keyboard.press('Tab');
    const focused = page.locator(':focus');
    const href = await focused.getAttribute('href');
    if (href?.includes('#/')) {
      await expect(focused).toBeVisible();
      return;
    }
  }
  throw new Error('Keyboard focus did not reach a semantic navigation link within 20 Tab presses.');
});
