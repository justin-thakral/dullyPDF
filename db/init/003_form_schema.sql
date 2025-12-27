--
-- 003_form_schema.sql
--
-- Extends the schema so a single view `vw_form_fields` exposes columns that
-- match database_fields.txt exactly. Underlying tables remain normalized; the
-- view flattens to a denormalized shape for CData / app consumption.

-- 1) Patients: add demographic, identifiers, contact, history, misc
ALTER TABLE public.patients
  ADD COLUMN IF NOT EXISTS middle_name TEXT,
  ADD COLUMN IF NOT EXISTS full_name TEXT,
  ADD COLUMN IF NOT EXISTS sex_at_birth TEXT,
  ADD COLUMN IF NOT EXISTS gender_identity TEXT,
  ADD COLUMN IF NOT EXISTS ssn_last_4 TEXT,
  ADD COLUMN IF NOT EXISTS marital_status TEXT,
  ADD COLUMN IF NOT EXISTS preferred_language TEXT,
  ADD COLUMN IF NOT EXISTS race TEXT,
  ADD COLUMN IF NOT EXISTS ethnicity TEXT,
  ADD COLUMN IF NOT EXISTS email_address TEXT,
  ADD COLUMN IF NOT EXISTS mobile_phone TEXT,
  ADD COLUMN IF NOT EXISTS home_phone TEXT,
  ADD COLUMN IF NOT EXISTS preferred_contact_method TEXT,
  ADD COLUMN IF NOT EXISTS address_line_2 TEXT,
  ADD COLUMN IF NOT EXISTS country TEXT,
  ADD COLUMN IF NOT EXISTS enterprise_patient_id TEXT,
  ADD COLUMN IF NOT EXISTS external_mrn TEXT,
  ADD COLUMN IF NOT EXISTS barcode_id TEXT,
  ADD COLUMN IF NOT EXISTS passport_number TEXT,
  ADD COLUMN IF NOT EXISTS driver_license_number TEXT,
  ADD COLUMN IF NOT EXISTS allergies_text TEXT,
  ADD COLUMN IF NOT EXISTS smoking_status TEXT,
  ADD COLUMN IF NOT EXISTS alcohol_use TEXT,
  ADD COLUMN IF NOT EXISTS pregnancy_status TEXT,
  ADD COLUMN IF NOT EXISTS chronic_conditions TEXT,
  ADD COLUMN IF NOT EXISTS past_surgical_history TEXT,
  ADD COLUMN IF NOT EXISTS family_history TEXT,
  ADD COLUMN IF NOT EXISTS preferred_pharmacy_name TEXT,
  ADD COLUMN IF NOT EXISTS preferred_pharmacy_phone TEXT,
  ADD COLUMN IF NOT EXISTS pharmacy_ncpdp TEXT,
  ADD COLUMN IF NOT EXISTS guardian_name TEXT,
  ADD COLUMN IF NOT EXISTS guarantor_name TEXT,
  ADD COLUMN IF NOT EXISTS guarantor_relationship TEXT,
  ADD COLUMN IF NOT EXISTS emergency_contact_name TEXT,
  ADD COLUMN IF NOT EXISTS emergency_contact_relationship TEXT,
  ADD COLUMN IF NOT EXISTS emergency_contact_phone TEXT,
  ADD COLUMN IF NOT EXISTS emergency_contact_email TEXT,
  ADD COLUMN IF NOT EXISTS notes TEXT,
  ADD COLUMN IF NOT EXISTS current_medications TEXT;

-- Backfill full_name for existing rows (first [middle] last)
UPDATE public.patients
SET full_name = CONCAT_WS(' ', first_name, NULLIF(middle_name, ''), last_name)
WHERE (full_name IS NULL OR full_name = '');

-- 2) Encounters: add visit, providers, facility, scheduling
ALTER TABLE public.encounters
  ADD COLUMN IF NOT EXISTS visit_number TEXT,
  ADD COLUMN IF NOT EXISTS reason_for_visit TEXT,
  ADD COLUMN IF NOT EXISTS triage_level TEXT,
  ADD COLUMN IF NOT EXISTS discharge_disposition TEXT,
  ADD COLUMN IF NOT EXISTS visit_status TEXT,
  ADD COLUMN IF NOT EXISTS attending_provider_name TEXT,
  ADD COLUMN IF NOT EXISTS attending_provider_npi TEXT,
  ADD COLUMN IF NOT EXISTS ordering_provider_name TEXT,
  ADD COLUMN IF NOT EXISTS ordering_provider_npi TEXT,
  ADD COLUMN IF NOT EXISTS referring_provider_name TEXT,
  ADD COLUMN IF NOT EXISTS referring_provider_npi TEXT,
  ADD COLUMN IF NOT EXISTS primary_care_provider TEXT,
  ADD COLUMN IF NOT EXISTS rendering_provider_npi TEXT,
  ADD COLUMN IF NOT EXISTS facility_name TEXT,
  ADD COLUMN IF NOT EXISTS facility_npi TEXT,
  ADD COLUMN IF NOT EXISTS facility_address TEXT,
  ADD COLUMN IF NOT EXISTS appointment_id TEXT,
  ADD COLUMN IF NOT EXISTS appointment_date DATE,
  ADD COLUMN IF NOT EXISTS appointment_time TIME,
  ADD COLUMN IF NOT EXISTS check_in_time TIME,
  ADD COLUMN IF NOT EXISTS check_out_time TIME,
  ADD COLUMN IF NOT EXISTS no_show_flag BOOLEAN,
  ADD COLUMN IF NOT EXISTS rescheduled_flag BOOLEAN;

-- 3) Insurance summary (primary/secondary)
CREATE TABLE IF NOT EXISTS public.insurance_summary (
  patient_id INTEGER PRIMARY KEY REFERENCES public.patients(id) ON DELETE CASCADE,
  primary_insurance_payer TEXT,
  primary_member_id TEXT,
  primary_group_number TEXT,
  primary_plan_name TEXT,
  secondary_insurance_payer TEXT,
  secondary_member_id TEXT,
  secondary_group_number TEXT,
  coverage_start_date DATE,
  coverage_end_date DATE,
  copay_amount NUMERIC(10,2),
  coinsurance_percentage NUMERIC(5,2),
  deductible_remaining NUMERIC(12,2),
  prior_auth_number TEXT,
  referral_required BOOLEAN
);

-- 4) Vitals per-encounter
CREATE TABLE IF NOT EXISTS public.vitals (
  id SERIAL PRIMARY KEY,
  encounter_id INTEGER NOT NULL REFERENCES public.encounters(id) ON DELETE CASCADE,
  height_cm NUMERIC(6,2),
  weight_kg NUMERIC(6,2),
  bmi NUMERIC(6,2),
  temperature_c NUMERIC(5,2),
  heart_rate_bpm INTEGER,
  respiratory_rate INTEGER,
  oxygen_saturation NUMERIC(5,2),
  blood_pressure_systolic INTEGER,
  blood_pressure_diastolic INTEGER,
  recorded_at TIMESTAMP DEFAULT NOW()
);

-- 5) Medications (latest)
CREATE TABLE IF NOT EXISTS public.medications (
  id SERIAL PRIMARY KEY,
  encounter_id INTEGER NOT NULL REFERENCES public.encounters(id) ON DELETE CASCADE,
  medication_name TEXT,
  medication_dose_mg NUMERIC(10,2),
  medication_route TEXT,
  medication_frequency TEXT,
  recorded_at TIMESTAMP DEFAULT NOW()
);

-- 6) Labs (latest)
CREATE TABLE IF NOT EXISTS public.labs (
  id SERIAL PRIMARY KEY,
  encounter_id INTEGER NOT NULL REFERENCES public.encounters(id) ON DELETE CASCADE,
  lab_order_id TEXT UNIQUE,
  lab_order_datetime TIMESTAMP,
  lab_test_name TEXT,
  lab_loinc_code TEXT,
  lab_result_value TEXT,
  lab_result_units TEXT,
  lab_result_flag TEXT,
  lab_collected_datetime TIMESTAMP,
  lab_reported_datetime TIMESTAMP
);

-- 7) Imaging (latest)
CREATE TABLE IF NOT EXISTS public.imaging (
  id SERIAL PRIMARY KEY,
  encounter_id INTEGER NOT NULL REFERENCES public.encounters(id) ON DELETE CASCADE,
  imaging_order_id TEXT,
  imaging_modality TEXT,
  imaging_body_part TEXT,
  radiology_report_impression TEXT,
  radiology_report_datetime TIMESTAMP
);

-- 8) Diagnoses and Procedures
CREATE TABLE IF NOT EXISTS public.diagnoses (
  id SERIAL PRIMARY KEY,
  encounter_id INTEGER NOT NULL REFERENCES public.encounters(id) ON DELETE CASCADE,
  primary_diagnosis_code TEXT,
  primary_diagnosis_description TEXT,
  secondary_diagnosis_code TEXT,
  secondary_diagnosis_description TEXT,
  icd10_code_1 TEXT,
  icd10_code_2 TEXT
);

CREATE TABLE IF NOT EXISTS public.procedures (
  id SERIAL PRIMARY KEY,
  encounter_id INTEGER NOT NULL REFERENCES public.encounters(id) ON DELETE CASCADE,
  cpt_code_1 TEXT,
  cpt_code_2 TEXT,
  procedure_datetime TIMESTAMP,
  anesthesia_minutes INTEGER
);

-- 9) Claims / Billing
CREATE TABLE IF NOT EXISTS public.claims (
  id SERIAL PRIMARY KEY,
  encounter_id INTEGER NOT NULL REFERENCES public.encounters(id) ON DELETE CASCADE,
  claim_number TEXT,
  claim_status TEXT,
  claim_submitted_date DATE,
  claim_paid_date DATE,
  total_charges NUMERIC(12,2),
  patient_responsibility NUMERIC(12,2),
  balance_due NUMERIC(12,2),
  payment_plan_active BOOLEAN,
  eob_date DATE,
  billing_notes TEXT
);

-- 10) Consents
CREATE TABLE IF NOT EXISTS public.consents (
  id SERIAL PRIMARY KEY,
  patient_id INTEGER UNIQUE NOT NULL REFERENCES public.patients(id) ON DELETE CASCADE,
  consent_for_treatment_signed BOOLEAN,
  hipaa_acknowledgement_date DATE,
  privacy_notice_signed BOOLEAN,
  assignment_of_benefits_signed BOOLEAN,
  telehealth_consent_signed BOOLEAN
);

-- Seed/updates for sample patient MRN100001
UPDATE public.patients SET
  middle_name = 'L',
  sex_at_birth = 'Female',
  gender_identity = 'Female',
  ssn_last_4 = '1234',
  marital_status = 'Single',
  preferred_language = 'English',
  race = 'Asian',
  ethnicity = 'Not Hispanic or Latino',
  email_address = 'ava.nguyen@example.com',
  mobile_phone = '555-123-4567',
  home_phone = '555-321-7654',
  preferred_contact_method = 'mobile_phone',
  address_line_2 = 'Apt 2B',
  country = 'USA',
  enterprise_patient_id = 'EID-0001',
  external_mrn = 'EXT-MRN-0001',
  barcode_id = 'BR-1001',
  passport_number = 'X12345678',
  driver_license_number = 'NYS-NG1234567',
  allergies_text = 'Penicillin',
  smoking_status = 'Never',
  alcohol_use = 'Occasional',
  pregnancy_status = 'N/A',
  chronic_conditions = 'Hypertension',
  past_surgical_history = 'Appendectomy (2010)',
  family_history = 'Father: diabetes',
  preferred_pharmacy_name = 'Acme Pharmacy',
  preferred_pharmacy_phone = '555-888-9900',
  pharmacy_ncpdp = '1234567',
  guardian_name = NULL,
  guarantor_name = 'L Nguyen',
  guarantor_relationship = 'Parent',
  emergency_contact_name = 'Minh Nguyen',
  emergency_contact_relationship = 'Father',
  emergency_contact_phone = '555-222-3333',
  emergency_contact_email = 'minh.nguyen@example.com',
  notes = 'Prefers morning appointments',
  current_medications = 'Lisinopril 10mg daily'
WHERE mrn = 'MRN100001';

-- Update encounters row for the same patient
UPDATE public.encounters e
SET visit_number = 'V-001',
    reason_for_visit = 'Follow-up',
    triage_level = '3',
    discharge_disposition = 'Home',
    visit_status = 'Closed',
    attending_provider_name = 'Dr. Julia Park',
    attending_provider_npi = '1234567890',
    ordering_provider_name = 'Dr. Julia Park',
    ordering_provider_npi = '1234567890',
    referring_provider_name = 'Dr. Sam Chen',
    referring_provider_npi = '0987654321',
    primary_care_provider = 'Dr. Alice Kim',
    rendering_provider_npi = '1122334455',
    facility_name = 'Downtown Clinic',
    facility_npi = '5566778899',
    facility_address = '100 Health Way, Albany, NY 12207',
    appointment_id = 'APT-1001',
    appointment_date = NOW()::date,
    appointment_time = '09:30',
    check_in_time = '09:20',
    check_out_time = '09:55',
    no_show_flag = false,
    rescheduled_flag = false
FROM public.patients p
WHERE e.patient_id = p.id AND p.mrn = 'MRN100001';

-- Seed vitals for that encounter
INSERT INTO public.vitals (encounter_id, height_cm, weight_kg, bmi, temperature_c, heart_rate_bpm, respiratory_rate, oxygen_saturation, blood_pressure_systolic, blood_pressure_diastolic)
SELECT e.id, 165.0, 62.0, 22.8, 36.8, 72, 16, 98.0, 118, 76
FROM public.encounters e JOIN public.patients p ON e.patient_id = p.id
WHERE p.mrn = 'MRN100001'
ON CONFLICT DO NOTHING;

-- Seed insurance summary
INSERT INTO public.insurance_summary (patient_id, primary_insurance_payer, primary_member_id, primary_group_number, primary_plan_name,
  secondary_insurance_payer, secondary_member_id, secondary_group_number,
  coverage_start_date, coverage_end_date, copay_amount, coinsurance_percentage, deductible_remaining, prior_auth_number, referral_required)
SELECT p.id, 'Acme Health', 'M-MRN100001', 'GRP-100', 'PPO Standard',
       'Backup Health', 'S-MRN100001', 'GRP-200',
       NOW()::date - INTERVAL '365 days', NULL, 25.00, 20.00, 500.00, 'AUTH-123', false
FROM public.patients p WHERE p.mrn = 'MRN100001'
ON CONFLICT (patient_id) DO NOTHING;

-- Seed medication
INSERT INTO public.medications (encounter_id, medication_name, medication_dose_mg, medication_route, medication_frequency)
SELECT e.id, 'Lisinopril', 10, 'PO', 'daily'
FROM public.encounters e JOIN public.patients p ON e.patient_id = p.id
WHERE p.mrn = 'MRN100001'
ON CONFLICT DO NOTHING;

-- Seed a lab
INSERT INTO public.labs (encounter_id, lab_order_id, lab_order_datetime, lab_test_name, lab_loinc_code, lab_result_value, lab_result_units, lab_result_flag, lab_collected_datetime, lab_reported_datetime)
SELECT e.id, 'LAB-1001', NOW() - INTERVAL '1 day', 'Hemoglobin A1c', '4548-4', '5.6', '%', 'N', NOW() - INTERVAL '1 day', NOW() - INTERVAL '20 hours'
FROM public.encounters e JOIN public.patients p ON e.patient_id = p.id
WHERE p.mrn = 'MRN100001'
ON CONFLICT DO NOTHING;

-- Seed imaging
INSERT INTO public.imaging (encounter_id, imaging_order_id, imaging_modality, imaging_body_part, radiology_report_impression, radiology_report_datetime)
SELECT e.id, 'IMG-2001', 'XR', 'Chest', 'No acute cardiopulmonary disease.', NOW() - INTERVAL '1 day'
FROM public.encounters e JOIN public.patients p ON e.patient_id = p.id
WHERE p.mrn = 'MRN100001'
ON CONFLICT DO NOTHING;

-- Seed diagnoses and procedures
INSERT INTO public.diagnoses (encounter_id, primary_diagnosis_code, primary_diagnosis_description, secondary_diagnosis_code, secondary_diagnosis_description, icd10_code_1, icd10_code_2)
SELECT e.id, 'I10', 'Essential (primary) hypertension', 'E11.9', 'Type 2 diabetes mellitus without complications', 'I10', 'E11.9'
FROM public.encounters e JOIN public.patients p ON e.patient_id = p.id
WHERE p.mrn = 'MRN100001'
ON CONFLICT DO NOTHING;

INSERT INTO public.procedures (encounter_id, cpt_code_1, cpt_code_2, procedure_datetime, anesthesia_minutes)
SELECT e.id, '93000', NULL, NOW() - INTERVAL '2 days', NULL
FROM public.encounters e JOIN public.patients p ON e.patient_id = p.id
WHERE p.mrn = 'MRN100001'
ON CONFLICT DO NOTHING;

-- Seed claims
INSERT INTO public.claims (encounter_id, claim_number, claim_status, claim_submitted_date, claim_paid_date, total_charges, patient_responsibility, balance_due, payment_plan_active, eob_date, billing_notes)
SELECT e.id, 'CLM-5001', 'Paid', (NOW() - INTERVAL '10 days')::date, (NOW() - INTERVAL '5 days')::date, 250.00, 50.00, 0.00, false, (NOW() - INTERVAL '5 days')::date, 'Processed successfully'
FROM public.encounters e JOIN public.patients p ON e.patient_id = p.id
WHERE p.mrn = 'MRN100001'
ON CONFLICT DO NOTHING;

-- Seed consents
INSERT INTO public.consents (patient_id, consent_for_treatment_signed, hipaa_acknowledgement_date, privacy_notice_signed, assignment_of_benefits_signed, telehealth_consent_signed)
SELECT p.id, true, (NOW() - INTERVAL '100 days')::date, true, true, true
FROM public.patients p WHERE p.mrn = 'MRN100001'
ON CONFLICT DO NOTHING;

-- 11) Denormalized view with columns matching database_fields.txt
CREATE OR REPLACE VIEW public.vw_form_fields AS
SELECT
  p.id AS patient_id,
  p.mrn,
  p.full_name,
  p.first_name,
  p.last_name,
  p.middle_name,
  p.dob AS date_of_birth,
  p.dob AS dob,
  -- Common aliases for mapping convenience
  COALESCE(p.email_address, NULL) AS email,
  COALESCE(p.mobile_phone, p.home_phone, p.phone) AS phone,
  p.postal_code AS zip,
  COALESCE(p.enterprise_patient_id, p.external_mrn, p.barcode_id) AS employee_id,
  NOW()::date AS date,
  p.sex_at_birth,
  p.gender_identity,
  p.ssn_last_4,
  p.marital_status,
  p.preferred_language,
  p.race,
  p.ethnicity,
  p.email_address,
  p.mobile_phone,
  p.home_phone,
  p.preferred_contact_method,
  p.street_address,
  p.address_line_2,
  p.city,
  p.state,
  p.postal_code,
  p.country,
  p.enterprise_patient_id,
  p.external_mrn,
  p.barcode_id,
  p.passport_number,
  p.driver_license_number,
  ins.primary_insurance_payer,
  ins.primary_member_id,
  ins.primary_group_number,
  ins.primary_plan_name,
  ins.secondary_insurance_payer,
  ins.secondary_member_id,
  ins.secondary_group_number,
  ins.coverage_start_date,
  ins.coverage_end_date,
  ins.copay_amount,
  ins.coinsurance_percentage,
  ins.deductible_remaining,
  ins.prior_auth_number,
  ins.referral_required,
  e.encounter_id,
  e.visit_number,
  e.admit_datetime,
  e.discharge_datetime,
  e.encounter_type,
  e.chief_complaint,
  e.reason_for_visit,
  e.triage_level,
  e.discharge_disposition,
  e.visit_status,
  e.attending_provider_name,
  e.attending_provider_npi,
  e.ordering_provider_name,
  e.ordering_provider_npi,
  e.referring_provider_name,
  e.referring_provider_npi,
  e.primary_care_provider,
  e.rendering_provider_npi,
  e.facility_name,
  e.facility_npi,
  e.facility_address,
  v.height_cm,
  v.weight_kg,
  v.bmi,
  v.temperature_c,
  v.heart_rate_bpm,
  v.respiratory_rate,
  v.oxygen_saturation,
  v.blood_pressure_systolic,
  v.blood_pressure_diastolic,
  p.allergies_text,
  p.smoking_status,
  p.alcohol_use,
  p.pregnancy_status,
  p.chronic_conditions,
  p.past_surgical_history,
  p.family_history,
  p.current_medications,
  m.medication_name,
  m.medication_dose_mg,
  m.medication_route,
  m.medication_frequency,
  m.recorded_at AS last_medication_update,
  l.lab_order_id,
  l.lab_order_datetime,
  l.lab_test_name,
  l.lab_loinc_code,
  l.lab_result_value,
  l.lab_result_units,
  l.lab_result_flag,
  l.lab_collected_datetime,
  l.lab_reported_datetime,
  i.imaging_order_id,
  i.imaging_modality,
  i.imaging_body_part,
  i.radiology_report_impression,
  i.radiology_report_datetime,
  d.primary_diagnosis_code,
  d.primary_diagnosis_description,
  d.secondary_diagnosis_code,
  d.secondary_diagnosis_description,
  d.icd10_code_1,
  d.icd10_code_2,
  pr.cpt_code_1,
  pr.cpt_code_2,
  pr.procedure_datetime,
  pr.anesthesia_minutes,
  c.claim_number,
  c.claim_status,
  c.claim_submitted_date,
  c.claim_paid_date,
  c.total_charges,
  c.patient_responsibility,
  c.balance_due,
  c.payment_plan_active,
  c.eob_date,
  c.billing_notes,
  con.consent_for_treatment_signed,
  con.hipaa_acknowledgement_date,
  con.privacy_notice_signed,
  con.assignment_of_benefits_signed,
  con.telehealth_consent_signed,
  p.emergency_contact_name,
  p.emergency_contact_relationship,
  p.emergency_contact_phone,
  p.emergency_contact_email,
  e.appointment_id,
  e.appointment_date,
  e.appointment_time,
  e.check_in_time,
  e.check_out_time,
  e.no_show_flag,
  e.rescheduled_flag,
  p.preferred_pharmacy_name,
  p.preferred_pharmacy_phone,
  p.pharmacy_ncpdp,
  p.guardian_name,
  p.guarantor_name,
  p.guarantor_relationship,
  p.notes
FROM public.patients p
LEFT JOIN public.insurance_summary ins ON ins.patient_id = p.id
LEFT JOIN public.encounters e ON e.patient_id = p.id
LEFT JOIN LATERAL (
  SELECT v.* FROM public.vitals v WHERE v.encounter_id = e.id ORDER BY v.recorded_at DESC NULLS LAST LIMIT 1
) v ON TRUE
LEFT JOIN LATERAL (
  SELECT m.* FROM public.medications m WHERE m.encounter_id = e.id ORDER BY m.recorded_at DESC NULLS LAST LIMIT 1
) m ON TRUE
LEFT JOIN LATERAL (
  SELECT l.* FROM public.labs l WHERE l.encounter_id = e.id ORDER BY l.lab_reported_datetime DESC NULLS LAST LIMIT 1
) l ON TRUE
LEFT JOIN LATERAL (
  SELECT i.* FROM public.imaging i WHERE i.encounter_id = e.id ORDER BY i.radiology_report_datetime DESC NULLS LAST LIMIT 1
) i ON TRUE
LEFT JOIN LATERAL (
  SELECT d.* FROM public.diagnoses d WHERE d.encounter_id = e.id ORDER BY d.id DESC LIMIT 1
) d ON TRUE
LEFT JOIN LATERAL (
  SELECT pr.* FROM public.procedures pr WHERE pr.encounter_id = e.id ORDER BY pr.procedure_datetime DESC NULLS LAST LIMIT 1
) pr ON TRUE
LEFT JOIN LATERAL (
  SELECT c.* FROM public.claims c WHERE c.encounter_id = e.id ORDER BY c.id DESC LIMIT 1
) c ON TRUE
LEFT JOIN public.consents con ON con.patient_id = p.id;
