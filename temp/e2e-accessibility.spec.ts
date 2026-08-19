import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { installContractMocks } from './mock-contracts';

async function assertNoSeriousViolations(page: Parameters<typeof AxeBuilder>[0]['page']) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((violation) => ['serious', 'critical'].includes(violation.impact ?? ''));
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await installContractMocks(page);
});

test('overview has no serious or critical axe violations', async ({ page }) => {
  await page.goto('/studio/#/overview');
  await expect(page.locator('main')).toBeVisible();
  await assertNoSeriousViolations(page);
});

test('reaction wheel workspace has no serious or critical axe violations', async ({ page }) => {
  await page.goto('/studio/#/spacecraft/reaction-wheels');
  await expect(page.locator('main')).toBeVisible();
  await assertNoSeriousViolations(page);
});
