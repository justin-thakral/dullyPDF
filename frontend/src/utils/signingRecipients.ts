export type SigningRecipientInput = {
  name: string;
  email: string;
  source: 'manual' | 'paste' | 'file';
};

export type SigningRecipientParseResult = {
  recipients: SigningRecipientInput[];
  rejected: string[];
};

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/i;

function isValidEmail(value: string): boolean {
  return EMAIL_PATTERN.test(value);
}

export function buildFallbackRecipientName(email: string): string {
  const localPart = String(email || '').trim().split('@')[0] || 'Signer';
  const pieces = localPart
    .split(/[._-]+/)
    .map((piece) => piece.trim())
    .filter(Boolean);
  if (!pieces.length) {
    return 'Signer';
  }
  return pieces
    .map((piece) => piece.charAt(0).toUpperCase() + piece.slice(1))
    .join(' ');
}

export function normalizeSigningRecipient(
  name: string | null | undefined,
  email: string | null | undefined,
  source: SigningRecipientInput['source'],
) {
  const normalizedEmail = String(email || '').trim().toLowerCase();
  if (!isValidEmail(normalizedEmail)) {
    return null;
  }
  const normalizedName = String(name || '').trim() || buildFallbackRecipientName(normalizedEmail);
  return {
    name: normalizedName,
    email: normalizedEmail,
    source,
  } satisfies SigningRecipientInput;
}

function parseAngleBracketRecipient(line: string, source: SigningRecipientInput['source']): SigningRecipientInput | null {
  const match = line.match(/^(.*?)<\s*([^>]+)\s*>$/);
  if (!match) {
    return null;
  }
  return normalizeSigningRecipient(match[1], match[2], source);
}

function parseCsvRow(line: string): string[] {
  const cells: string[] = [];
  let current = '';
  let insideQuotes = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    const next = line[index + 1];
    if (character === '"') {
      if (insideQuotes && next === '"') {
        current += '"';
        index += 1;
        continue;
      }
      insideQuotes = !insideQuotes;
      continue;
    }
    if (character === ',' && !insideQuotes) {
      cells.push(current.trim());
      current = '';
      continue;
    }
    current += character;
  }
  cells.push(current.trim());
  return cells;
}

function parseRecipientLine(
  line: string,
  source: SigningRecipientInput['source'],
  options: { csvMode: boolean },
): SigningRecipientInput | null {
  const { csvMode } = options;
  const trimmed = line.trim();
  if (!trimmed) {
    return null;
  }
  const angleRecipient = parseAngleBracketRecipient(trimmed, source);
  if (angleRecipient) {
    return angleRecipient;
  }

  const csvCells = csvMode ? parseCsvRow(trimmed) : [];
  if (csvCells.length >= 2) {
    const [first, second] = csvCells;
    if (isValidEmail(first)) {
      return normalizeSigningRecipient(second, first, source);
    }
    if (isValidEmail(second)) {
      return normalizeSigningRecipient(first, second, source);
    }
  }

  if (csvCells.length === 1 && isValidEmail(csvCells[0])) {
    return normalizeSigningRecipient(null, csvCells[0], source);
  }

  if (!csvMode && trimmed.includes(',')) {
    const tokens = trimmed.split(',').map((entry) => entry.trim()).filter(Boolean);
    if (tokens.length === 2) {
      if (isValidEmail(tokens[0])) {
        return normalizeSigningRecipient(tokens[1], tokens[0], source);
      }
      if (isValidEmail(tokens[1])) {
        return normalizeSigningRecipient(tokens[0], tokens[1], source);
      }
    }
  }

  if (isValidEmail(trimmed)) {
    return normalizeSigningRecipient(null, trimmed, source);
  }
  return null;
}

export function mergeSigningRecipients(
  existing: SigningRecipientInput[],
  additions: SigningRecipientInput[],
): SigningRecipientInput[] {
  const seen = new Set<string>();
  const merged: SigningRecipientInput[] = [];
  for (const entry of [...existing, ...additions]) {
    const emailKey = String(entry.email || '').trim().toLowerCase();
    if (!emailKey || seen.has(emailKey)) {
      continue;
    }
    seen.add(emailKey);
    merged.push({
      name: String(entry.name || '').trim() || buildFallbackRecipientName(emailKey),
      email: emailKey,
      source: entry.source,
    });
  }
  return merged;
}

export function parseSigningRecipientsFromText(
  rawText: string,
  options: {
    source: SigningRecipientInput['source'];
    csvMode?: boolean;
  },
): SigningRecipientParseResult {
  const { source, csvMode = false } = options;
  const recipients: SigningRecipientInput[] = [];
  const rejected: string[] = [];
  const lines = String(rawText || '')
    .split(/\r?\n/)
    .map((entry) => entry.trim())
    .filter(Boolean);
  if (!lines.length) {
    return { recipients, rejected };
  }

  let startIndex = 0;
  if (csvMode) {
    const headerCells = parseCsvRow(lines[0]).map((entry) => entry.trim().toLowerCase());
    if (headerCells.includes('email') || headerCells.includes('e-mail')) {
      startIndex = 1;
    }
  }

  for (const line of lines.slice(startIndex)) {
    const recipient = parseRecipientLine(line, source, { csvMode });
    if (recipient) {
      recipients.push(recipient);
    } else {
      rejected.push(line);
    }
  }

  return {
    recipients: mergeSigningRecipients([], recipients),
    rejected,
  };
}

export async function parseSigningRecipientsFromFile(file: File): Promise<SigningRecipientParseResult> {
  const name = String(file?.name || '').trim().toLowerCase();
  const csvMode = name.endsWith('.csv');
  const text = await file.text();
  return parseSigningRecipientsFromText(text, {
    source: 'file',
    csvMode,
  });
}
