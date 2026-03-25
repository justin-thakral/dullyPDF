import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ApiFillManagerDialog from '../../../../src/components/features/ApiFillManagerDialog';
import type { ApiFillManagerDialogProps } from '../../../../src/hooks/useWorkspaceTemplateApi';

function createProps(overrides: Partial<ApiFillManagerDialogProps> = {}): ApiFillManagerDialogProps {
  return {
    open: true,
    onClose: vi.fn(),
    templateName: 'Patient Intake',
    hasActiveTemplate: true,
    endpoint: null,
    schema: null,
    limits: null,
    recentEvents: [],
    loading: false,
    publishing: false,
    rotating: false,
    revoking: false,
    error: null,
    latestSecret: null,
    onPublish: vi.fn().mockResolvedValue(undefined),
    onRotate: vi.fn().mockResolvedValue(undefined),
    onRevoke: vi.fn().mockResolvedValue(undefined),
    onRefresh: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe('ApiFillManagerDialog', () => {
  it('publishes with the selected export mode', async () => {
    const user = userEvent.setup();
    const onPublish = vi.fn().mockResolvedValue(undefined);

    render(<ApiFillManagerDialog {...createProps({ onPublish })} />);

    await user.click(screen.getByRole('button', { name: /Editable PDF/i }));
    await user.click(screen.getByRole('button', { name: 'Generate key' }));

    expect(onPublish).toHaveBeenCalledWith('editable');
  });

  it('uses the published schema export mode when republishing an existing endpoint', async () => {
    const user = userEvent.setup();
    const onPublish = vi.fn().mockResolvedValue(undefined);

    render(
      <ApiFillManagerDialog
        {...createProps({
          onPublish,
          endpoint: {
            id: 'tep-1',
            templateId: 'tpl-1',
            templateName: 'Patient Intake',
            status: 'active',
            snapshotVersion: 3,
            keyPrefix: 'dpa_live_abc123',
            createdAt: '2026-03-25T12:00:00.000Z',
            updatedAt: '2026-03-25T12:00:00.000Z',
            publishedAt: '2026-03-25T12:00:00.000Z',
            lastUsedAt: '2026-03-25T13:00:00.000Z',
            usageCount: 7,
            fillPath: '/api/v1/fill/tep-1.pdf',
            schemaPath: '/api/template-api-endpoints/tep-1/schema',
          },
          schema: {
            snapshotVersion: 3,
            defaultExportMode: 'editable',
            fields: [{ key: 'full_name', fieldName: 'full_name', type: 'text', page: 1 }],
            checkboxFields: [],
            checkboxGroups: [],
            radioGroups: [],
            exampleData: { full_name: 'Ada Lovelace' },
          },
        })}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Republish snapshot' }));

    expect(onPublish).toHaveBeenCalledWith('editable');
  });

  it('shows generate key for revoked endpoints because publish creates a new secret', () => {
    render(
      <ApiFillManagerDialog
        {...createProps({
          endpoint: {
            id: 'tep-1',
            templateId: 'tpl-1',
            templateName: 'Patient Intake',
            status: 'revoked',
            snapshotVersion: 3,
            keyPrefix: 'dpa_live_abc123',
            createdAt: '2026-03-25T12:00:00.000Z',
            updatedAt: '2026-03-25T12:00:00.000Z',
            publishedAt: '2026-03-25T12:00:00.000Z',
            lastUsedAt: '2026-03-25T13:00:00.000Z',
            usageCount: 7,
            fillPath: '/api/v1/fill/tep-1.pdf',
            schemaPath: '/api/template-api-endpoints/tep-1/schema',
          },
          schema: {
            snapshotVersion: 3,
            defaultExportMode: 'flat',
            fields: [{ key: 'full_name', fieldName: 'full_name', type: 'text', page: 1 }],
            checkboxFields: [],
            checkboxGroups: [],
            radioGroups: [],
            exampleData: { full_name: 'Ada Lovelace' },
          },
        })}
      />,
    );

    expect(screen.getByRole('button', { name: 'Generate key' })).toBeTruthy();
    expect(screen.getByText(/This endpoint is revoked\./)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Copy URL' })).toBeNull();
    expect(screen.queryByText('cURL')).toBeNull();
  });

  it('renders code examples with the published export mode', () => {
    render(
      <ApiFillManagerDialog
        {...createProps({
          endpoint: {
            id: 'tep-1',
            templateId: 'tpl-1',
            templateName: 'Patient Intake',
            status: 'active',
            snapshotVersion: 3,
            keyPrefix: 'dpa_live_abc123',
            createdAt: '2026-03-25T12:00:00.000Z',
            updatedAt: '2026-03-25T12:00:00.000Z',
            publishedAt: '2026-03-25T12:00:00.000Z',
            lastUsedAt: '2026-03-25T13:00:00.000Z',
            usageCount: 7,
            fillPath: '/api/v1/fill/tep-1.pdf',
            schemaPath: '/api/template-api-endpoints/tep-1/schema',
          },
          schema: {
            snapshotVersion: 3,
            defaultExportMode: 'editable',
            fields: [{ key: 'full_name', fieldName: 'full_name', type: 'text', page: 1 }],
            checkboxFields: [],
            checkboxGroups: [],
            radioGroups: [],
            exampleData: { full_name: 'Ada Lovelace' },
          },
        })}
      />,
    );

    expect(screen.getAllByText(/"exportMode": "editable"/).length).toBeGreaterThan(0);
    expect(screen.getByText(/exportMode: "editable"/)).toBeTruthy();
  });

  it('renders endpoint metadata, schema counts, and one-time secret details', () => {
    render(
      <ApiFillManagerDialog
        {...createProps({
          endpoint: {
            id: 'tep-1',
            templateId: 'tpl-1',
            templateName: 'Patient Intake',
            status: 'active',
            snapshotVersion: 3,
            keyPrefix: 'dpa_live_abc123',
            createdAt: '2026-03-25T12:00:00.000Z',
            updatedAt: '2026-03-25T12:00:00.000Z',
            publishedAt: '2026-03-25T12:00:00.000Z',
            lastUsedAt: '2026-03-25T13:00:00.000Z',
            usageCount: 7,
            fillPath: '/api/v1/fill/tep-1.pdf',
            schemaPath: '/api/template-api-endpoints/tep-1/schema',
          },
          latestSecret: 'dpa_live_secret',
          schema: {
            snapshotVersion: 3,
            defaultExportMode: 'flat',
            fields: [{ key: 'full_name', fieldName: 'full_name', type: 'text', page: 1 }],
            checkboxFields: [{ key: 'agree_to_terms', fieldName: 'agree_to_terms', type: 'checkbox', page: 1 }],
            checkboxGroups: [
              {
                key: 'consent_signed',
                groupKey: 'consent_group',
                type: 'checkbox_rule',
                operation: 'yes_no',
                options: [{ optionKey: 'yes', optionLabel: 'Yes', fieldName: 'i_consent_yes' }],
                trueOption: 'yes',
                falseOption: 'no',
                valueMap: null,
              },
            ],
            radioGroups: [
              {
                groupKey: 'marital_status',
                type: 'radio',
                options: [{ optionKey: 'single', optionLabel: 'Single' }],
              },
            ],
            exampleData: {
              full_name: '<full_name>',
              agree_to_terms: true,
              consent_signed: true,
              marital_status: 'single',
            },
          },
          limits: {
            activeEndpointsMax: 1,
            activeEndpointsUsed: 1,
            requestsPerMonthMax: 250,
            requestsThisMonth: 7,
            requestUsageMonth: '2026-03',
            maxPagesPerRequest: 25,
            templatePageCount: 2,
          },
          recentEvents: [
            {
              id: 'evt-1',
              eventType: 'rotated',
              outcome: 'success',
              createdAt: '2026-03-25T13:00:00.000Z',
              snapshotVersion: 3,
              summary: 'API key rotated',
              metadata: { keyPrefix: 'dpa_live_abc123' },
            },
          ],
        })}
      />,
    );

    expect(screen.getByText('Shown once')).toBeTruthy();
    expect(screen.getByText('dpa_live_secret')).toBeTruthy();
    expect(screen.getByText('Snapshot version')).toBeTruthy();
    expect(screen.getByText('7')).toBeTruthy();
    expect(screen.getByText('Limits and activity')).toBeTruthy();
    expect(screen.getByText('Mar 2026')).toBeTruthy();
    expect(screen.getByText('Recent activity')).toBeTruthy();
    expect(screen.getByText('API key rotated')).toBeTruthy();
    expect(screen.getByText('Scalar fields')).toBeTruthy();
    expect(screen.getByText('Checkbox groups')).toBeTruthy();
    expect(screen.getByText('Radio groups')).toBeTruthy();
    expect(screen.getByText('cURL')).toBeTruthy();
    expect(screen.getByText('Node')).toBeTruthy();
    expect(screen.getByText('Python')).toBeTruthy();
  });
});
