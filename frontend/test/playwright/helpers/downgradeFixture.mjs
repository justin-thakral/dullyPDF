import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const helperDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(helperDir, '..', '..', '..', '..');
const frontendEnvPaths = [
  path.join(repoRoot, 'frontend/.env.local'),
  path.join(repoRoot, 'env/frontend.dev.env'),
];

function readFrontendEnvValue(key) {
  for (const frontendEnvPath of frontendEnvPaths) {
    if (!fs.existsSync(frontendEnvPath)) {
      continue;
    }
    const source = fs.readFileSync(frontendEnvPath, 'utf8');
    const line = source
      .split('\n')
      .find((entry) => entry.trim().startsWith(`${key}=`));
    if (line) {
      return line.split('=').slice(1).join('=').trim();
    }
  }
  throw new Error(`Missing ${key} in frontend env files: ${frontendEnvPaths.join(', ')}`);
}

function runBackendPython(script, extraEnv = {}) {
  const backendEnvFile = process.env.PW_BACKEND_ENV_FILE || 'env/backend.dev.env';
  const bashScript = `
set -euo pipefail
# Export the dev env file so Python inherits the intended Firebase project and
# secret settings even when the parent shell already has other values loaded.
set -a
source "$PW_BACKEND_ENV_FILE"
set +a
source scripts/_load_firebase_secret.sh
if [[ "\${PW_USE_FIREBASE_SECRET_FOR_ADMIN_HELPERS:-true}" == "true" ]] && [[ -n "\${FIREBASE_CREDENTIALS_SECRET:-}" ]]; then
  load_firebase_secret
  export FIREBASE_USE_ADC=false
  unset FIREBASE_SERVICE_ACCOUNT_ID
elif [[ "\${FIREBASE_USE_ADC:-}" == "true" ]] && [[ -z "\${FIREBASE_SERVICE_ACCOUNT_ID:-}" ]] && [[ -n "\${BACKEND_RUNTIME_SERVICE_ACCOUNT:-}" ]]; then
  export FIREBASE_SERVICE_ACCOUNT_ID="$BACKEND_RUNTIME_SERVICE_ACCOUNT"
elif [[ "\${FIREBASE_USE_ADC:-}" != "true" ]]; then
  load_firebase_secret
fi
backend/.venv/bin/python - <<'PY'
${script}
PY
`;
  return execFileSync('bash', ['-lc', bashScript], {
    cwd: repoRoot,
    env: { ...process.env, PW_BACKEND_ENV_FILE: backendEnvFile, ...extraEnv },
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  }).trim();
}

function runWithTimeout(operation, label, timeoutMs = 10000) {
  let timeoutId = null;
  const timeoutPromise = new Promise((_, reject) => {
    timeoutId = setTimeout(() => {
      reject(new Error(`${label} timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  });
  return Promise.race([
    operation().finally(() => {
      if (timeoutId !== null) {
        clearTimeout(timeoutId);
      }
    }),
    timeoutPromise,
  ]);
}

export function createCustomToken(uid) {
  const output = runBackendPython(
    `
from firebase_admin import auth
from backend.firebaseDB.firebase_service import init_firebase
import os

uid = os.environ["PW_UID"]
init_firebase()
print(auth.create_custom_token(uid).decode())
`,
    { PW_UID: uid },
  );
  return output.split('\n').pop();
}

export function verifyEmailUser(uid) {
  runBackendPython(
    `
from firebase_admin import auth
from backend.firebaseDB.firebase_service import init_firebase
import os

uid = os.environ["PW_UID"]
init_firebase()
auth.update_user(uid, email_verified=True)
print("ok")
`,
    { PW_UID: uid },
  );
}

export async function createHybridEmailUser(page) {
  const apiKey = readFrontendEnvValue('VITE_FIREBASE_API_KEY');
  const email = `codex-downgrade-${Date.now()}@example.com`;
  const password = 'CodexDowngrade!234';
  const result = await page.evaluate(async ({ apiKey, email, password }) => {
    const response = await fetch(`https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=${apiKey}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, returnSecureToken: true }),
    });
    const data = await response.json();
    return { ok: response.ok, data };
  }, { apiKey, email, password });

  if (!result.ok) {
    throw new Error(`Failed to create Firebase test user: ${JSON.stringify(result.data)}`);
  }

  // Real workspace bootstrap now blocks unverified accounts. Mark the seeded
  // Firebase user as verified so browser-based smoke flows can reach the
  // authenticated workspace/profile paths they are meant to exercise.
  verifyEmailUser(result.data.localId);

  return {
    apiKey,
    email,
    password,
    uid: result.data.localId,
    initialIdToken: result.data.idToken,
  };
}

export async function signInWithCustomTokenHarness(page, customToken) {
  return runWithTimeout(() => page.evaluate(async (token) => {
    const authHarness = await import('/src/testSupport/playwrightAuthHarness.ts');
    return authHarness.signInWithCustomTokenForPlaywright(token);
  }, customToken), 'signInWithCustomTokenHarness');
}

export async function signOutHarness(page) {
  await runWithTimeout(() => page.evaluate(async () => {
    const authHarness = await import('/src/testSupport/playwrightAuthHarness.ts');
    await authHarness.signOutForPlaywright();
  }), 'signOutHarness');
}

export async function deleteCurrentUserHarness(page) {
  return runWithTimeout(() => page.evaluate(async () => {
    const authHarness = await import('/src/testSupport/playwrightAuthHarness.ts');
    return authHarness.deleteCurrentUserForPlaywright();
  }), 'deleteCurrentUserHarness');
}

export async function deleteUserByInitialToken(page, apiKey, idToken) {
  await runWithTimeout(() => page.evaluate(async ({ apiKey, idToken }) => {
    await fetch(`https://identitytoolkit.googleapis.com/v1/accounts:delete?key=${apiKey}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ idToken }),
    });
  }, { apiKey, idToken }), 'deleteUserByInitialToken');
}

export function seedDowngradedAccountFixture({ uid, email }) {
  const output = runBackendPython(
    `
import json
import os

from backend.firebaseDB.fill_link_database import FILL_LINKS_COLLECTION
from backend.firebaseDB.firebase_service import get_firestore_client, init_firebase
from backend.firebaseDB.group_database import GROUPS_COLLECTION
from backend.firebaseDB.template_database import TEMPLATES_COLLECTION
from backend.firebaseDB.user_database import (
    activate_pro_membership,
    downgrade_to_base_membership,
    set_user_billing_subscription,
)
from backend.services.downgrade_retention_service import apply_user_downgrade_retention

uid = os.environ["PW_UID"]
email = os.environ["PW_EMAIL"]
init_firebase()
client = get_firestore_client()
user_ref = client.collection("app_users").document(uid)
user_ref.set(
    {
        "firebase_uid": uid,
        "email": email,
        "displayName": "Downgrade Test User",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    },
    merge=True,
)

templates = [
    ("tpl-alpha", "Intake Form Alpha", "2026-01-01T00:00:00+00:00"),
    ("tpl-beta", "Consent Form Beta", "2026-01-02T00:00:00+00:00"),
    ("tpl-gamma", "Referral Gamma", "2026-01-03T00:00:00+00:00"),
    ("tpl-delta", "Follow Up Delta", "2026-01-04T00:00:00+00:00"),
]
template_ids = []
for suffix, name, created_at in templates:
    template_id = f"{uid}-{suffix}"
    template_ids.append(template_id)
    client.collection(TEMPLATES_COLLECTION).document(template_id).set(
        {
            "user_id": uid,
            "pdf_bucket_path": f"fixtures/{uid}/{suffix}.pdf",
            "template_bucket_path": f"fixtures/{uid}/{suffix}.json",
            "metadata": {"name": name},
            "created_at": created_at,
            "updated_at": created_at,
        }
    )

group_id = f"{uid}-group"
client.collection(GROUPS_COLLECTION).document(group_id).set(
    {
        "user_id": uid,
        "name": "Admissions",
        "normalized_name": "admissions",
        "template_ids": template_ids,
        "created_at": "2026-01-05T00:00:00+00:00",
        "updated_at": "2026-01-05T00:00:00+00:00",
    }
)

questions = [{"key": "full_name", "label": "Full Name", "type": "text", "requiredForRespondentIdentity": True}]
link_payloads = [
    ("link-alpha", template_ids[0], "Alpha Link", "2026-01-05T00:00:00+00:00"),
    ("link-beta", template_ids[1], "Beta Link", "2026-01-06T00:00:00+00:00"),
    ("link-delta", template_ids[3], "Delta Link", "2026-01-07T00:00:00+00:00"),
]
for suffix, template_id, title, created_at in link_payloads:
    link_id = f"{uid}-{suffix}"
    client.collection(FILL_LINKS_COLLECTION).document(link_id).set(
        {
            "user_id": uid,
            "scope_type": "template",
            "template_id": template_id,
            "template_name": title.replace(" Link", ""),
            "template_ids": [template_id],
            "title": title,
            "public_token": f"{link_id}-token",
            "status": "active",
            "closed_reason": None,
            "response_count": 0,
            "questions": questions,
            "require_all_fields": False,
            "created_at": created_at,
            "updated_at": created_at,
            "published_at": created_at,
            "closed_at": None,
        }
    )

activate_pro_membership(uid, stripe_event_id=f"evt_seed_upgrade_{uid}", reset_monthly_credits=True)
set_user_billing_subscription(
    uid,
    customer_id=f"cus_{uid}",
    subscription_id=f"sub_{uid}",
    subscription_status="active",
    subscription_price_id="price_pro_monthly",
    cancel_at_period_end=False,
    cancel_at=None,
    current_period_end=None,
)
downgrade_to_base_membership(uid)
set_user_billing_subscription(
    uid,
    customer_id=f"cus_{uid}",
    subscription_id=f"sub_{uid}",
    subscription_status="canceled",
    subscription_price_id="price_pro_monthly",
    cancel_at_period_end=True,
    cancel_at=1775000000,
    current_period_end=1775000000,
)
summary = apply_user_downgrade_retention(uid)
print(json.dumps({"templateIds": template_ids, "groupId": group_id, "summary": summary}, sort_keys=True))
`,
    { PW_UID: uid, PW_EMAIL: email },
  );
  return JSON.parse(output.split('\n').pop());
}

export function seedStaleProRetentionFixture({ uid, email }) {
  const output = runBackendPython(
    `
import json
import os

from backend.firebaseDB.firebase_service import get_firestore_client, init_firebase
from backend.firebaseDB.group_database import GROUPS_COLLECTION
from backend.firebaseDB.template_database import TEMPLATES_COLLECTION
from backend.firebaseDB.user_database import DOWNGRADE_RETENTION_FIELD

uid = os.environ["PW_UID"]
email = os.environ["PW_EMAIL"]
init_firebase()
client = get_firestore_client()

templates = [
    ("tpl-alpha", "Intake Form Alpha", "2026-01-01T00:00:00+00:00"),
    ("tpl-beta", "Consent Form Beta", "2026-01-02T00:00:00+00:00"),
    ("tpl-gamma", "Referral Gamma", "2026-01-03T00:00:00+00:00"),
    ("tpl-delta", "Follow Up Delta", "2026-01-04T00:00:00+00:00"),
]
template_ids = []
for suffix, name, created_at in templates:
    template_id = f"{uid}-{suffix}"
    template_ids.append(template_id)
    client.collection(TEMPLATES_COLLECTION).document(template_id).set(
        {
            "user_id": uid,
            "pdf_bucket_path": f"fixtures/{uid}/{suffix}.pdf",
            "template_bucket_path": f"fixtures/{uid}/{suffix}.json",
            "metadata": {"name": name},
            "created_at": created_at,
            "updated_at": created_at,
        }
    )

group_id = f"{uid}-group"
client.collection(GROUPS_COLLECTION).document(group_id).set(
    {
        "user_id": uid,
        "name": "Admissions",
        "normalized_name": "admissions",
        "template_ids": template_ids,
        "created_at": "2026-01-05T00:00:00+00:00",
        "updated_at": "2026-01-05T00:00:00+00:00",
    }
)

client.collection("app_users").document(uid).set(
    {
        "firebase_uid": uid,
        "email": email,
        "displayName": "Stale Retention User",
        "role": "pro",
        "stripe_customer_id": f"cus_{uid}",
        "stripe_subscription_id": f"sub_{uid}",
        "stripe_subscription_status": "active",
        "stripe_subscription_price_id": "price_pro_monthly",
        DOWNGRADE_RETENTION_FIELD: {
            "status": "grace_period",
            "policy_version": 1,
            "downgraded_at": "2026-03-01T00:00:00+00:00",
            "grace_ends_at": "2026-03-31T00:00:00+00:00",
            "saved_forms_limit": 3,
            "kept_template_ids": template_ids[:3],
            "pending_delete_template_ids": [template_ids[3]],
            "pending_delete_link_ids": [f"{uid}-link-delta"],
            "updated_at": "2026-03-10T00:00:00+00:00",
        },
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-03-10T00:00:00+00:00",
    },
    merge=True,
)
print(json.dumps({"templateIds": template_ids, "groupId": group_id}, sort_keys=True))
`,
    { PW_UID: uid, PW_EMAIL: email },
  );
  return JSON.parse(output.split('\n').pop());
}

export function readFixtureState(uid) {
  const output = runBackendPython(
    `
import json
import os

from backend.firebaseDB.fill_link_database import list_fill_links
from backend.firebaseDB.firebase_service import get_firestore_client, init_firebase
from backend.firebaseDB.group_database import list_groups
from backend.firebaseDB.template_database import list_templates

uid = os.environ["PW_UID"]
init_firebase()
client = get_firestore_client()
user_snapshot = client.collection("app_users").document(uid).get()
user_data = user_snapshot.to_dict() or {}
retention = user_data.get("downgrade_retention")
templates = [
    {"id": record.id, "name": record.name, "createdAt": record.created_at}
    for record in list_templates(uid)
]
links = [
    {
        "id": record.id,
        "templateId": record.template_id,
        "status": record.status,
        "closedReason": record.closed_reason,
    }
    for record in list_fill_links(uid)
]
groups = [
    {"id": record.id, "name": record.name, "templateIds": record.template_ids}
    for record in list_groups(uid)
]
print(json.dumps({
    "role": user_data.get("role"),
    "retention": retention,
    "templates": templates,
    "links": links,
    "groups": groups,
    "subscriptionStatus": user_data.get("stripe_subscription_status"),
    "subscriptionId": user_data.get("stripe_subscription_id"),
}, sort_keys=True))
`,
    { PW_UID: uid },
  );
  return JSON.parse(output.split('\n').pop());
}

export function cleanupFixture(uid) {
  runBackendPython(
    `
import os

from backend.firebaseDB.fill_link_database import delete_fill_link, list_fill_links
from backend.firebaseDB.firebase_service import get_firestore_client, init_firebase
from backend.firebaseDB.group_database import delete_group, list_groups
from backend.firebaseDB.template_database import delete_template, list_templates

uid = os.environ["PW_UID"]
init_firebase()
for record in list_fill_links(uid):
    delete_fill_link(record.id, uid)
for record in list_groups(uid):
    delete_group(record.id, uid)
for record in list_templates(uid):
    delete_template(record.id, uid)
client = get_firestore_client()
client.collection("app_users").document(uid).delete()
print("ok")
`,
    { PW_UID: uid },
  );
}
