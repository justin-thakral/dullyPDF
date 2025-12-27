from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import fitz  # PyMuPDF
import requests

from ..combinedSrc.config import get_logger
from .render_raw_dataset import render_pdfs_to_dataset


USER_AGENT = "pdf-form-dataset-builder/1.0 (+https://github.com/justin-thakral/pdf)"
REQUEST_TIMEOUT = 30
logger = get_logger(__name__)


OPEN_LICENSES = {
    "mit",
    "apache-2.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "cc0-1.0",
    "cc-by-4.0",
    "cc-by-sa-4.0",
    "unlicense",
    "isc",
    "mpl-2.0",
}


SEARCH_QUERIES: List[Tuple[str, str]] = [
    ("hipaa form pdf in:name,description,readme", "hipaa_authorization"),
    ("authorization form pdf in:name,description,readme", "hipaa_authorization"),
    ("release of information form pdf in:name,description,readme", "hipaa_release"),
    ("notice of privacy practices pdf in:name,description,readme", "hipaa_notice"),
    ("patient intake form pdf in:name,description,readme", "patient_intake"),
    ("patient registration form pdf in:name,description,readme", "patient_registration"),
    ("medical history form pdf in:name,description,readme", "medical_history"),
    ("consent to treat form pdf in:name,description,readme", "consent_treat"),
    ("financial policy form pdf in:name,description,readme", "financial_policy"),
    ("pediatric intake form pdf in:name,description,readme", "pediatric_intake"),
    ("dental intake form pdf in:name,description,readme", "dental_intake"),
    ("behavioral health intake form pdf in:name,description,readme", "behavioral_health_intake"),
    ("telehealth consent form pdf in:name,description,readme", "telehealth_consent"),
    ("patient forms pdf in:name,description,readme", "patient_intake"),
]


CATEGORY_KEYWORDS: List[Tuple[str, str]] = [
    ("notice of privacy practices", "hipaa_notice"),
    ("privacy practices", "hipaa_notice"),
    ("hipaa", "hipaa_authorization"),
    ("release of information", "hipaa_release"),
    ("roi", "hipaa_release"),
    ("authorization", "hipaa_authorization"),
    ("pediatric", "pediatric_intake"),
    ("dental", "dental_intake"),
    ("behavioral health", "behavioral_health_intake"),
    ("mental health", "behavioral_health_intake"),
    ("telehealth", "telehealth_consent"),
    ("patient registration", "patient_registration"),
    ("registration", "patient_registration"),
    ("demographics", "patient_registration"),
    ("medical history", "medical_history"),
    ("history questionnaire", "medical_history"),
    ("consent to treat", "consent_treat"),
    ("financial policy", "financial_policy"),
    ("intake", "patient_intake"),
]


FOLDER_BY_CATEGORY: Dict[str, str] = {
    "hipaa_authorization": "hipaa",
    "hipaa_release": "hipaa",
    "hipaa_notice": "hipaa",
    "patient_registration": "intake",
    "patient_intake": "intake",
    "medical_history": "intake",
    "pediatric_intake": "intake",
    "dental_intake": "intake",
    "behavioral_health_intake": "intake",
    "consent_treat": "consent",
    "financial_policy": "consent",
    "telehealth_consent": "consent",
}

CATEGORY_CAPS: Dict[str, int] = {
    "hipaa_authorization": 30,
    "hipaa_release": 30,
    "hipaa_notice": 20,
    "patient_registration": 20,
    "patient_intake": 25,
    "medical_history": 25,
    "consent_treat": 20,
    "financial_policy": 15,
    "pediatric_intake": 15,
    "dental_intake": 15,
    "behavioral_health_intake": 15,
    "telehealth_consent": 15,
}

FORM_PATH_KEYWORDS = [
    "form",
    "intake",
    "questionnaire",
    "consent",
    "authorization",
    "release",
    "registration",
    "history",
    "notice",
    "privacy",
    "policy",
    "acknowledgment",
    "acknowledgement",
    "patient",
    "hipaa",
    "survey",
]

SEARCH_SLEEP_S = 1.1
REPO_SEARCH_MIN_INTERVAL_S = 2.5
REPO_SEARCH_MAX_PAGES = 2
MAX_PDF_BYTES = 25 * 1024 * 1024

SEED_PDF_URLS: List[Tuple[str, str]] = [
    ("pediatric_intake", "https://milestonepediatrics.org/client_files/file/new-patient-intake.pdf"),
    ("pediatric_intake", "https://northeastpeds.com/wp-content/uploads/New-patient-intake.pdf"),
    ("pediatric_intake", "https://sa1s3.patientpop.com/assets/docs/164883.pdf"),
    ("pediatric_intake", "https://www.brightfutures.org/mentalhealth/pdf/professionals/ped_intake_form.pdf"),
    (
        "pediatric_intake",
        "https://cnyfamilycare.org/wp-content/uploads/2023/11/2020-PEDIATRIC-PATIENT-INTAKE-FORM.pdf",
    ),
    ("pediatric_intake", "https://irp.cdn-website.com/fb4ab164/files/uploaded/PediatricIntakeForm.pdf"),
    (
        "pediatric_intake",
        "https://www.avenamedical.com/uploads/3/1/1/8/31180947/avena_pediatric_intake_form__fillable_.pdf",
    ),
    (
        "pediatric_intake",
        "https://agapefamilymedicalcenter.com/wp-content/uploads/2020/11/Pediatric-New-Patient-Intake-Form.pdf",
    ),
    ("pediatric_intake", "https://rowanmedicine.com/documents/pediatric-new-patient-form.pdf"),
    ("dental_intake", "https://www.southwestdentalgroupsmiles.com/pdfs/new-patient-forms.pdf"),
    ("dental_intake", "https://www.rubensteindentalgroup.com/wp-content/uploads/2020/11/DentalIntakeForm.pdf"),
    ("dental_intake", "https://www.lovenationaldental.com/pdf/new-patient-package.pdf"),
    (
        "dental_intake",
        "https://www.ada.org/-/media/project/ada-organization/ada/ada-org/files/publications/guidelines-for-practice-success/mngpatients_patient_intake.pdf?rev=a12b131b799d4f6ba3d287697e64f960&hash=EF75288030191064E85313DF0D5DC005",
    ),
    (
        "dental_intake",
        "https://langleyhealth.com/wp-content/uploads/2025/08/DENTAL-Patient-Intake-Packet-revised-8-21-2025.pdf",
    ),
    ("dental_intake", "https://robisondental.com/wp-content/uploads/2023/02/Patient-Intake-Form.pdf"),
    (
        "dental_intake",
        "https://wildwooddentalclinic.com/wp-content/uploads/2020/05/New-Patient-Intake-Form-FILLABLE.pdf",
    ),
    (
        "dental_intake",
        "https://assets-global.website-files.com/600754479f70fb2c4d356be6/63a4c6bcf8cc9173372476ef_Dental%20New%20Patient%20Form%20copy.pdf",
    ),
    ("dental_intake", "https://setonkc.org/wp-content/uploads/2024/03/Dental-Intake-Form-English.docx.pdf"),
    (
        "dental_intake",
        "https://www.naturaldentures.com/wp-content/uploads/2025/03/New-Patient-Forms-3-10-25.pdf",
    ),
    (
        "behavioral_health_intake",
        "https://www.aacap.org/App_Themes/AACAP/docs/member_resources/toolbox_for_clinical_practice_and_outcomes/history/CAP_Intake_Form_3.pdf",
    ),
    (
        "behavioral_health_intake",
        "https://nlccwi.org/wp-content/uploads/2024/01/BH-Intake-Adult-Forms-Fillable-01-2024.pdf",
    ),
    ("behavioral_health_intake", "https://www.psyfamilyservices.com/1_intake_questionnaire_adult.pdf"),
    (
        "behavioral_health_intake",
        "https://www.aetna.com/content/dam/aetna/pdfs/aetnacom/healthcare-professionals/documents-forms/behavioral-health-biopsychosocial-intake-form.pdf",
    ),
    (
        "behavioral_health_intake",
        "https://www.onvidahealth.org/wp-content/uploads/2024/08/Behavioral-Health-Adult-Intake-form-Fillable-Revised-8.19.24.pdf",
    ),
    ("behavioral_health_intake", "https://www.imindjackson.com/wp-content/uploads/2020/10/Intake-Form_iMind_NEW.pdf"),
    (
        "behavioral_health_intake",
        "https://irp.cdn-website.com/667cdec7/files/uploaded/BH_Intake_New_September_2024_English_Fillable.pdf",
    ),
    ("behavioral_health_intake", "https://compgihealth.com/wp-content/uploads/2025/04/Behavioral-Health-Intake-Form-1.pdf"),
    (
        "behavioral_health_intake",
        "https://www.ohsu.edu/sites/default/files/2025-07/SHW-Fillable-Behavioral-Health-Intake-Form-with-Billing-Accessible.pdf",
    ),
    ("behavioral_health_intake", "https://chcfhc.org/files/galleries/BH_1_Intake_Screening_Form_ENGLISH.pdf"),
    (
        "behavioral_health_intake",
        "https://manhattanpsychologygroup.com/wp-content/uploads/2024/08/Mental-Health-Intake-Form_-Adult-Digital.pdf",
    ),
    (
        "behavioral_health_intake",
        "https://www.carilionclinic.org/sites/default/files/2024-12/Pediatric%20Behavioral%20Health_Intake%20packet%202024.pdf",
    ),
    (
        "telehealth_consent",
        "https://familystrategies.org/files/Client%20Paperwork/Telehealth%20Consent%202024%20Fillable.pdf",
    ),
    (
        "telehealth_consent",
        "https://www.acep.org/siteassets/sites/geda/media/documnets/telehealth/sample-telehealth-consent-form.pdf",
    ),
    ("telehealth_consent", "https://naswassurance.org/pdf/telehealth-informed-consent.pdf"),
    (
        "telehealth_consent",
        "https://irp.cdn-website.com/08f25be0/files/uploaded/Telehealth_Consent_Form_%28Fillable%29.pdf",
    ),
    ("telehealth_consent", "https://coendo.com/wp-content/uploads/telehealth-consent-3-29-21fillable-2.pdf"),
    (
        "telehealth_consent",
        "https://www.umtrc.org/clientuploads/Resources/Sample%20Forms%20and%20Templates/Sample_Informed_Consent_for_Telemedicine_Services.pdf",
    ),
    ("telehealth_consent", "https://ctmentalhealth.net/wp-content/uploads/Telehealth.pdf"),
]

_LAST_REPO_SEARCH_TS = 0.0


@dataclass
class DownloadRecord:
    slug: str
    category: str
    url: str
    retrieved_at: str
    license_note: str
    review_needed: bool
    sha256: str
    pages: Optional[int]
    path: Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", (value or "").strip()).strip("_")
    return cleaned.lower() or "form"


def _category_from_text(text: str, hint: str) -> str:
    lowered = (text or "").lower()
    for keyword, category in CATEGORY_KEYWORDS:
        if keyword in lowered:
            return category
    return hint or "misc"


def _folder_for_category(category: str) -> str:
    return FOLDER_BY_CATEGORY.get(category, "misc")


def _ensure_dirs(root: Path) -> None:
    for folder in ("hipaa", "intake", "consent", "misc"):
        (root / folder).mkdir(parents=True, exist_ok=True)


def _load_existing_sources(csv_path: Path) -> Tuple[Set[str], Set[str]]:
    hashes: Set[str] = set()
    urls: Set[str] = set()
    if not csv_path.exists():
        return hashes, urls
    with csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            sha = (row.get("sha256") or "").strip()
            url = (row.get("url") or "").strip()
            if sha:
                hashes.add(sha)
            if url:
                urls.add(url)
    return hashes, urls


def _load_existing_category_counts(csv_path: Path) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    if not csv_path.exists():
        return counts
    with csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            category = (row.get("category") or "").strip()
            if not category:
                continue
            counts[category] = counts.get(category, 0) + 1
    return counts


def _write_sources_row(csv_path: Path, record: DownloadRecord) -> None:
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                record.slug,
                record.category,
                record.url,
                record.retrieved_at,
                record.license_note,
                "true" if record.review_needed else "false",
                record.sha256,
                "" if record.pages is None else str(record.pages),
            ]
        )


def _get_pages(pdf_path: Path) -> Optional[int]:
    try:
        with fitz.open(pdf_path) as doc:
            return int(doc.page_count)
    except Exception:
        return None


def _robots_allows(url: str, user_agent: str, cache: Dict[str, RobotFileParser]) -> bool:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if base not in cache:
        rp = RobotFileParser()
        robots_url = f"{base}/robots.txt"
        try:
            resp = requests.get(robots_url, headers={"User-Agent": user_agent}, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp = None
        except Exception:
            rp = None
        cache[base] = rp
    rp = cache.get(base)
    if rp is None:
        return True
    return rp.can_fetch(user_agent, url)


def _download_pdf(
    session: requests.Session,
    url: str,
    out_dir: Path,
    slug_base: str,
    seen_hashes: Set[str],
    user_agent: str,
    robots_cache: Dict[str, RobotFileParser],
    github_token: Optional[str],
) -> Tuple[Optional[Path], Optional[str]]:
    headers = {"User-Agent": user_agent}
    request_url = url
    if "api.github.com" in url and github_token:
        headers["Authorization"] = f"Bearer {github_token}"
        headers["Accept"] = "application/vnd.github.raw"
    else:
        if not _robots_allows(url, user_agent, robots_cache):
            return None, "robots_disallow"

    try:
        resp = session.get(request_url, headers=headers, timeout=REQUEST_TIMEOUT, stream=True)
    except Exception:
        return None, "request_failed"

    if resp.status_code != 200:
        return None, f"http_{resp.status_code}"

    content_type = (resp.headers.get("content-type") or "").lower()
    temp_path = out_dir / f"{slug_base}.tmp"
    hasher = hashlib.sha256()
    wrote = False
    try:
        with temp_path.open("wb") as handle:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                if not wrote:
                    wrote = True
                handle.write(chunk)
                hasher.update(chunk)
    finally:
        resp.close()

    if not wrote:
        temp_path.unlink(missing_ok=True)
        return None, "empty_body"

    sha256 = hasher.hexdigest()
    if sha256 in seen_hashes:
        temp_path.unlink(missing_ok=True)
        return None, "duplicate"

    with temp_path.open("rb") as handle:
        signature = handle.read(5)
    if signature != b"%PDF-":
        temp_path.unlink(missing_ok=True)
        return None, "not_pdf"

    if "pdf" not in content_type and "application/octet-stream" not in content_type:
        # Some servers send application/octet-stream for PDFs; allow those.
        pass

    final_name = f"{slug_base}_{sha256[:10]}.pdf"
    final_path = out_dir / final_name
    temp_path.rename(final_path)
    seen_hashes.add(sha256)
    return final_path, sha256


def _normalize_source_url(url: str) -> str:
    """
    Normalize source URLs so GitHub blob/raw links become direct raw downloads.

    This avoids HTML responses when rehydrating PDFs from sources.csv.
    """
    if not url:
        return url
    parsed = urlparse(url)
    netloc = (parsed.netloc or "").lower()
    if netloc in {"github.com", "www.github.com"}:
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 4 and parts[2] in {"blob", "raw"}:
            owner, repo, _, branch = parts[:4]
            rel_path = "/".join(parts[4:])
            return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{rel_path}"
    return url


def _download_pdf_to_path(
    session: requests.Session,
    url: str,
    dest_path: Path,
    *,
    expected_sha: Optional[str],
    user_agent: str,
    robots_cache: Dict[str, RobotFileParser],
    github_token: Optional[str],
    max_bytes: Optional[int],
) -> Tuple[bool, str]:
    """
    Download a PDF to an explicit path while verifying content type and SHA.

    Returns (ok, reason) where reason is the failure tag or a summary string.
    """
    normalized_url = _normalize_source_url(url)
    request_url = requests.utils.requote_uri(normalized_url)
    headers = {"User-Agent": user_agent}
    if "api.github.com" in request_url and github_token:
        headers["Authorization"] = f"Bearer {github_token}"
        headers["Accept"] = "application/vnd.github.raw"
    else:
        if not _robots_allows(request_url, user_agent, robots_cache):
            return False, "robots_disallow"

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_suffix(".tmp")
    hasher = hashlib.sha256()
    wrote = False
    total = 0
    max_exceeded = False

    try:
        resp = session.get(request_url, headers=headers, timeout=REQUEST_TIMEOUT, stream=True)
    except Exception as exc:
        return False, f"request_failed: {exc}"

    try:
        if resp.status_code != 200:
            return False, f"http_{resp.status_code}"

        with temp_path.open("wb") as handle:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                wrote = True
                handle.write(chunk)
                hasher.update(chunk)
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    max_exceeded = True
                    break
    finally:
        resp.close()

    if max_exceeded:
        temp_path.unlink(missing_ok=True)
        return False, "max_bytes_exceeded"

    if not wrote:
        temp_path.unlink(missing_ok=True)
        return False, "empty_body"

    with temp_path.open("rb") as handle:
        signature = handle.read(5)
    if signature != b"%PDF-":
        temp_path.unlink(missing_ok=True)
        return False, "not_pdf"

    sha256 = hasher.hexdigest()
    expected_sha = (expected_sha or "").strip()
    if expected_sha and sha256 != expected_sha:
        temp_path.unlink(missing_ok=True)
        return False, "sha_mismatch"

    temp_path.replace(dest_path)
    return True, sha256


def _iter_sources_rows(csv_path: Path) -> Iterable[Dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def download_from_sources_csv(
    *,
    out_root: Path,
    sources_csv: Path,
    sleep_s: float,
    max_bytes: Optional[int],
) -> Dict[str, int]:
    """
    Download missing PDFs listed in sources.csv into the raw dataset folders.
    """
    rows = _iter_sources_rows(sources_csv)
    if not rows:
        logger.info("No sources found at %s", sources_csv)
        return {"downloaded": 0, "skipped": 0, "failed": 0}

    pdf_root = out_root / "pdfs"
    _ensure_dirs(pdf_root)
    session = requests.Session()
    robots_cache: Dict[str, RobotFileParser] = {}
    github_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")

    downloaded = 0
    skipped = 0
    failed = 0

    for row in rows:
        if (row.get("review_needed") or "").strip().lower() == "true":
            logger.debug("Skipping review-needed source: %s", row.get("slug"))
            skipped += 1
            continue
        slug = (row.get("slug") or "").strip()
        url = (row.get("url") or "").strip()
        category = (row.get("category") or "").strip()
        if not slug or not url:
            logger.info("Skipping source with missing slug/url: %s", row)
            failed += 1
            continue

        folder = _folder_for_category(category)
        dest_path = pdf_root / folder / f"{slug}.pdf"
        if dest_path.exists():
            skipped += 1
            continue

        time.sleep(sleep_s)
        ok, reason = _download_pdf_to_path(
            session,
            url,
            dest_path,
            expected_sha=row.get("sha256"),
            user_agent=USER_AGENT,
            robots_cache=robots_cache,
            github_token=github_token,
            max_bytes=max_bytes,
        )
        if ok:
            logger.info("Downloaded %s", dest_path)
            downloaded += 1
        else:
            logger.info("Failed to download %s (%s)", slug, reason)
            failed += 1

    logger.info("sources.csv sync complete: downloaded=%s skipped=%s failed=%s", downloaded, skipped, failed)
    return {"downloaded": downloaded, "skipped": skipped, "failed": failed}


def _sleep_until_repo_search_budget() -> None:
    """
    Enforce a minimum interval between GitHub repository search calls.

    GitHub search endpoints are rate-limited (~30 requests per minute). This guard keeps the
    downloader from triggering a hard rate-limit during long runs.
    """
    global _LAST_REPO_SEARCH_TS
    now = time.time()
    wait = REPO_SEARCH_MIN_INTERVAL_S - (now - _LAST_REPO_SEARCH_TS)
    if wait > 0:
        time.sleep(wait)
    _LAST_REPO_SEARCH_TS = time.time()


def _wait_for_search_reset(token: str) -> None:
    resp = requests.get(
        "https://api.github.com/rate_limit",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
        },
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        time.sleep(65)
        return
    data = resp.json()
    reset = data.get("resources", {}).get("search", {}).get("reset")
    remaining = data.get("resources", {}).get("search", {}).get("remaining")
    now = int(time.time())
    if remaining and int(remaining) > 0:
        return
    if reset and int(reset) > now:
        time.sleep(int(reset) - now + 2)
    else:
        time.sleep(65)


def _github_repo_search(query: str, page: int) -> List[Dict]:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        raise RuntimeError(
            "GitHub repository search requires authentication. Set GITHUB_TOKEN (or GH_TOKEN) "
            "to a personal access token with public_repo scope."
        )
    _sleep_until_repo_search_budget()
    params = {"q": query, "per_page": 50, "page": page}
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
    }
    resp = requests.get(
        "https://api.github.com/search/repositories",
        params=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        if resp.status_code == 403 and "rate limit" in (resp.text or "").lower():
            _wait_for_search_reset(token)
            resp = requests.get(
                "https://api.github.com/search/repositories",
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        if resp.status_code != 200:
            raise RuntimeError(f"GitHub search failed ({resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    return data.get("items", [])


def _license_from_repo(repo: Dict) -> Tuple[str, bool]:
    lic = repo.get("license") or {}
    spdx = (lic.get("spdx_id") or "").strip().lower()
    name = (lic.get("name") or "").strip()
    repo_name = (repo.get("full_name") or "").strip()
    suffix = f" ({repo_name})" if repo_name else ""
    if spdx and spdx.lower() in OPEN_LICENSES:
        return f"GitHub license {spdx}{suffix}", False
    if spdx and spdx.lower() != "noassertion":
        return f"GitHub license {spdx}{suffix}", True
    if name:
        return f"GitHub license {name}{suffix}", True
    return "No repo license metadata", True


def _list_repo_pdfs(repo_full_name: str, default_branch: str, token: str) -> List[Tuple[str, Optional[int]]]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
    }
    tree_url = f"https://api.github.com/repos/{repo_full_name}/git/trees/{default_branch}"
    resp = requests.get(
        tree_url, headers=headers, params={"recursive": "1"}, timeout=REQUEST_TIMEOUT
    )
    if resp.status_code != 200:
        return []
    data = resp.json()
    if data.get("truncated"):
        return []
    pdfs: List[Tuple[str, Optional[int]]] = []
    for node in data.get("tree", []):
        if node.get("type") != "blob":
            continue
        path = node.get("path") or ""
        if not path.lower().endswith(".pdf"):
            continue
        size = node.get("size")
        pdfs.append((path, size))
    return pdfs


def _license_from_url(url: str) -> Tuple[str, bool]:
    host = urlparse(url).netloc.lower()
    if host.endswith(".gov") or host.endswith(".mil"):
        return f"US Government source ({host})", False
    return f"Web source ({host}) license unknown", True


def _iter_seed_links() -> Iterable[Tuple[str, str, str, str, str, bool]]:
    for category, url in SEED_PDF_URLS:
        lowered = url.lower()
        if ".pdf" not in lowered:
            continue
        license_note, review_needed = _license_from_url(url)
        yield url, url, category, url, license_note, review_needed


def _iter_candidate_links() -> Iterable[Tuple[str, str, str, str, str, bool]]:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required for repo discovery.")

    seen_repos: Set[str] = set()
    for query, category in SEARCH_QUERIES:
        for page in range(1, REPO_SEARCH_MAX_PAGES + 1):
            for repo in _github_repo_search(query, page):
                full_name = repo.get("full_name") or ""
                if not full_name or full_name in seen_repos:
                    continue
                seen_repos.add(full_name)
                default_branch = repo.get("default_branch") or "main"
                license_note, review_needed = _license_from_repo(repo)
                pdf_paths = _list_repo_pdfs(full_name, default_branch, token)
                for path, size in pdf_paths:
                    lowered_path = path.lower()
                    if not any(keyword in lowered_path for keyword in FORM_PATH_KEYWORDS):
                        continue
                    if size and size > MAX_PDF_BYTES:
                        continue
                    text_hint = f"{path} {repo.get('name','')} {query}"
                    category_hint = _category_from_text(text_hint, category)
                    source_url = f"https://github.com/{full_name}/blob/{default_branch}/{path}"
                    api_url = (
                        f"https://api.github.com/repos/{full_name}/contents/{path}?ref={default_branch}"
                    )
                    yield api_url, source_url, category_hint, text_hint, license_note, review_needed
            time.sleep(SEARCH_SLEEP_S)


def download_dataset(
    *,
    out_root: Path,
    target: int,
    sleep_s: float,
    use_seeds: bool,
    use_github: bool,
) -> List[DownloadRecord]:
    pdf_root = out_root / "pdfs"
    sources_csv = out_root / "sources.csv"
    _ensure_dirs(pdf_root)

    seen_hashes, seen_urls = _load_existing_sources(sources_csv)
    category_counts = _load_existing_category_counts(sources_csv)
    robots_cache: Dict[str, RobotFileParser] = {}
    session = requests.Session()
    github_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")

    downloaded: List[DownloadRecord] = []
    total_attempts = 0

    def handle_candidate(
        api_url: str,
        source_url: str,
        category_hint: str,
        text_hint: str,
        license_note: str,
        review_needed: bool,
        prefer_hint: bool,
    ) -> bool:
        nonlocal total_attempts
        if len(downloaded) >= target:
            return False
        if source_url in seen_urls:
            return True

        category = category_hint if prefer_hint else _category_from_text(text_hint, category_hint)
        cap = CATEGORY_CAPS.get(category, target)
        if category_counts.get(category, 0) >= cap:
            return True
        total_attempts += 1
        time.sleep(sleep_s)
        folder = _folder_for_category(category)
        dest_dir = pdf_root / folder
        dest_dir.mkdir(parents=True, exist_ok=True)

        slug_base = _slugify(Path(urlparse(source_url or api_url).path).stem)
        file_path, sha256 = _download_pdf(
            session,
            api_url,
            dest_dir,
            slug_base,
            seen_hashes,
            USER_AGENT,
            robots_cache,
            github_token,
        )
        if not file_path or not sha256:
            return True

        retrieved_at = datetime.now(tz=timezone.utc).isoformat()
        pages = _get_pages(file_path)
        slug = file_path.stem
        record = DownloadRecord(
            slug=slug,
            category=category,
            url=source_url or api_url,
            retrieved_at=retrieved_at,
            license_note=license_note,
            review_needed=review_needed,
            sha256=sha256,
            pages=pages,
            path=file_path,
        )
        _write_sources_row(sources_csv, record)
        if source_url:
            seen_urls.add(source_url)
        downloaded.append(record)
        category_counts[category] = category_counts.get(category, 0) + 1
        return True

    if use_seeds:
        for api_url, source_url, category_hint, text_hint, license_note, review_needed in _iter_seed_links():
            if not handle_candidate(
                api_url, source_url, category_hint, text_hint, license_note, review_needed, True
            ):
                break

    if use_github and len(downloaded) < target:
        for api_url, source_url, category_hint, text_hint, license_note, review_needed in _iter_candidate_links():
            if not handle_candidate(
                api_url, source_url, category_hint, text_hint, license_note, review_needed, False
            ):
                break

    return downloaded


def _load_ingest_paths(csv_path: Path) -> List[Path]:
    paths: List[Path] = []
    if not csv_path.exists():
        return paths
    pdf_root = csv_path.parent / "pdfs"
    with csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if (row.get("review_needed") or "").strip().lower() == "true":
                continue
            slug = (row.get("slug") or "").strip()
            category = (row.get("category") or "").strip()
            if not slug:
                continue
            folder = _folder_for_category(category)
            pdf_path = pdf_root / folder / f"{slug}.pdf"
            if pdf_path.exists():
                paths.append(pdf_path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Download public PDF forms and ingest them.")
    parser.add_argument("--target", type=int, default=200, help="Number of PDFs to download.")
    parser.add_argument("--sleep", type=float, default=1.3, help="Seconds to sleep between requests.")
    parser.add_argument("--skip-ingest", action="store_true", help="Skip rendering PDFs into images/meta.")
    parser.add_argument("--skip-seeds", action="store_true", help="Skip curated seed URLs.")
    parser.add_argument("--skip-github", action="store_true", help="Skip GitHub-based discovery.")
    parser.add_argument(
        "--from-sources",
        action="store_true",
        help="Download PDFs listed in sources.csv (skip new discovery).",
    )
    parser.add_argument(
        "--sources",
        type=Path,
        default=None,
        help="Path to sources.csv (defaults to <repo>/backend/sandbox/ML/data/raw/sources.csv).",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=None,
        help="Maximum bytes to download per PDF (omit for no limit).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Skip PDFs with more than this many pages during ingestion.",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    out_root = repo_root / "backend" / "sandbox" / "ml" / "data" / "raw"
    out_root.mkdir(parents=True, exist_ok=True)
    sources_csv = args.sources or (out_root / "sources.csv")
    max_bytes = int(args.max_bytes) if args.max_bytes is not None and args.max_bytes > 0 else None

    if args.from_sources:
        if not sources_csv.exists():
            raise SystemExit(f"sources.csv not found: {sources_csv}")
        download_from_sources_csv(
            out_root=out_root,
            sources_csv=sources_csv,
            sleep_s=float(args.sleep),
            max_bytes=max_bytes,
        )
    else:
        if not sources_csv.exists():
            sources_csv.write_text(
                "slug,category,url,retrieved_at,license_note,review_needed,sha256,pages\n",
                encoding="utf-8",
            )
        download_dataset(
            out_root=out_root,
            target=int(args.target),
            sleep_s=float(args.sleep),
            use_seeds=not args.skip_seeds,
            use_github=not args.skip_github,
        )

    if args.skip_ingest:
        return

    ingest_paths = _load_ingest_paths(sources_csv)
    if ingest_paths:
        render_pdfs_to_dataset(
            ingest_paths,
            out_dir=out_root,
            dpi=int(os.getenv("SANDBOX_DPI", "500")),
            overwrite=False,
            max_pages=args.max_pages,
        )


if __name__ == "__main__":
    main()
