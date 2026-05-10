import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Global setup — runs once per `npx playwright test` invocation, before any
 * worker spawns. We use it to truncate the cumulative axe-violations log so
 * each suite run produces a clean dataset.
 */
export default async function globalSetup(): Promise<void> {
  const reportDir = path.resolve(__dirname, 'reports');
  fs.mkdirSync(reportDir, { recursive: true });
  const log = process.env.PW_VIOLATIONS_LOG ?? path.join(reportDir, 'axe-violations.jsonl');
  try {
    fs.writeFileSync(log, '');
  } catch {
    /* noop */
  }
}
