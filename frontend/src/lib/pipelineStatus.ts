import contract from "../../../shared/pipeline_status_contract.json";

type ContractColumn = {
  id: string;
  label: string;
  target_status: string;
  statuses: string[];
};

type Contract = {
  statuses: string[];
  human_editable_statuses: string[];
  pre_draft_cleanup_statuses: string[];
  draft_startable_statuses: string[];
  columns: ContractColumn[];
  transitions: Record<string, string[]>;
};

const pipelineContract = contract as Contract;

export const VALID_STATUSES = new Set(pipelineContract.statuses);
export const HUMAN_EDITABLE_STATUSES = new Set(
  pipelineContract.human_editable_statuses
);
export const DRAFT_STARTABLE_STATUSES = new Set(
  pipelineContract.draft_startable_statuses
);
export const PIPELINE_COLUMNS = pipelineContract.columns;

export function getColumnForStatus(status: string): string {
  const column = PIPELINE_COLUMNS.find((item) => item.statuses.includes(status));
  return column?.id ?? "rejected";
}

export function canStartDraftFromStatus(status: string): boolean {
  return DRAFT_STARTABLE_STATUSES.has(status);
}
