import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const REPO_ROOT_REAL = fs.realpathSync(REPO_ROOT);

export function assertWorkingDirectoryWithinRepo(serverLabel = 'dullypdf-mcp') {
  const cwdReal = fs.realpathSync(process.cwd());
  const relative = path.relative(REPO_ROOT_REAL, cwdReal);
  const isInsideRepo =
    relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
  if (isInsideRepo) return;
  // eslint-disable-next-line no-console
  console.error(
    `[${serverLabel}] Refusing to start outside the repo. Current: ${cwdReal}. Repo root: ${REPO_ROOT_REAL}.`
  );
  process.exit(1);
}

export function asAbsolutePath(inputPath) {
  if (typeof inputPath !== 'string' || !inputPath.trim()) return null;
  return path.isAbsolute(inputPath) ? inputPath : path.resolve(REPO_ROOT, inputPath);
}

export { REPO_ROOT };
