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

export function isPathWithinRepo(candidatePath) {
  if (typeof candidatePath !== 'string' || !candidatePath.trim()) return false;
  try {
    const realPath = fs.realpathSync(candidatePath);
    const relative = path.relative(REPO_ROOT_REAL, realPath);
    return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
  } catch {
    return false;
  }
}

export function assertPathWithinRepo(candidatePath, label = 'path') {
  if (isPathWithinRepo(candidatePath)) return;
  throw new Error(`Refusing to access ${label} outside the repo: ${candidatePath}`);
}

export { REPO_ROOT };
