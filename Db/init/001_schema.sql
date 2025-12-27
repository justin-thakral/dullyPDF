--
-- 001_schema.sql
--
-- Creates a minimal healthcare schema with a few core tables and seed data
-- suitable for read-only access via CData Connect Cloud. These tables are
-- intentionally simple so you can iterate quickly and add columns over time.

-- Patients
CREATE TABLE IF NOT EXISTS public.patients (
  id SERIAL PRIMARY KEY,
  mrn TEXT UNIQUE NOT NULL,
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  dob DATE,
  phone TEXT,
  street_address TEXT,
  city TEXT,
  state TEXT,
  postal_code TEXT
);

-- Encounters (visits)
CREATE TABLE IF NOT EXISTS public.encounters (
  id SERIAL PRIMARY KEY,
  encounter_id TEXT UNIQUE NOT NULL,
  patient_id INTEGER NOT NULL REFERENCES public.patients(id) ON DELETE CASCADE,
  admit_datetime TIMESTAMP,
  discharge_datetime TIMESTAMP,
  encounter_type TEXT,
  chief_complaint TEXT
);

-- Insurance (simple payer info)
CREATE TABLE IF NOT EXISTS public.insurance (
  id SERIAL PRIMARY KEY,
  patient_id INTEGER NOT NULL REFERENCES public.patients(id) ON DELETE CASCADE,
  payer_name TEXT,
  member_id TEXT,
  group_number TEXT,
  coverage_start_date DATE,
  coverage_end_date DATE
);

-- A view exposing a common join used by reporting/CData consumers
CREATE OR REPLACE VIEW public.vw_patients_encounters AS
SELECT p.id               AS patient_pk,
       p.mrn,
       p.first_name,
       p.last_name,
       p.dob,
       e.encounter_id,
       e.admit_datetime,
       e.discharge_datetime,
       e.encounter_type,
       e.chief_complaint
FROM public.patients p
LEFT JOIN public.encounters e ON e.patient_id = p.id;

-- Seed data (non-PII, fictional)
INSERT INTO public.patients (mrn, first_name, last_name, dob, phone, street_address, city, state, postal_code)
VALUES
  ('MRN100001', 'Ava',    'Nguyen',  '1990-05-01', '555-123-4567', '10 Pine St', 'Albany',    'NY', '12207'),
  ('MRN100002', 'Diego',  'Martinez','1986-09-15', '555-987-6543', '44 Oak Ave', 'Hartford',  'CT', '06103'),
  ('MRN100003', 'Priya',  'Patel',   '1978-12-22', '555-222-1100', '72 Elm Rd',  'Trenton',   'NJ', '08608')
ON CONFLICT (mrn) DO NOTHING;

INSERT INTO public.encounters (encounter_id, patient_id, admit_datetime, discharge_datetime, encounter_type, chief_complaint)
SELECT 'ENC-' || p.mrn, p.id, NOW() - INTERVAL '2 days', NOW() - INTERVAL '1 day', 'outpatient', 'Follow-up'
FROM public.patients p
ON CONFLICT DO NOTHING;

INSERT INTO public.insurance (patient_id, payer_name, member_id, group_number, coverage_start_date)
SELECT p.id, 'Acme Health', 'M-' || p.mrn, 'GRP-100', NOW()::date - INTERVAL '365 days'
FROM public.patients p
ON CONFLICT DO NOTHING;

