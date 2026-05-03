import type { BatchStatus, DocumentState, IngestionJobStatus, ReviewState, StageState } from '../types'

export default function StatusBadge({ value }: { value: BatchStatus | DocumentState | StageState | ReviewState | IngestionJobStatus }) {
  const label = value.replace(/_/g, ' ')
  return <span className={`badge badge-${value.replace(/_/g, '-')}`}>{label}</span>
}
