import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { installContractMocks } from './mock-contracts';

async function assertNoSeriousViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((violation) => ['serious', 'critical'].includes(violation.impact ?? ''));
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await installContractMocks(page);
});

test('overview has no serious or critical axe violations', async ({ page }) => {
  await page.goto('/studio/');
  await expect(page.locator('main')).toBeVisible();
  await assertNoSeriousViolations(page);
});

test('reaction wheel workspace has no serious or critical axe violations', async ({ page }) => {
  await page.goto('/studio/spacecraft/actuators');
  await expect(page.locator('main')).toBeVisible();
  await assertNoSeriousViolations(page);
});
