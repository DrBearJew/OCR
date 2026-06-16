import type { BatchStatus, DocumentState, IngestionJobStatus, ReviewState, StageState } from '../types'
import { useI18n } from '../i18n'

export default function StatusBadge({ value }: { value: BatchStatus | DocumentState | StageState | ReviewState | IngestionJobStatus }) {
  const { t } = useI18n()
  const label = t(`status.${value}`, value.replace(/_/g, ' '))
  return <span className={`badge badge-${value.replace(/_/g, '-')}`}>{label}</span>
}
