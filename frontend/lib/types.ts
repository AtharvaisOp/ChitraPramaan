export type Candidate = {
  index: number;
  url: string;
  title: string;
  thumbnail_url: string;
  source: string;
  score: number;
};

export type SessionResponse = {
  session_id: string;
  status: "auto_selected" | "review_required";
  selection_method: "auto" | null;
  selected_candidate: Candidate | null;
  candidates: Candidate[];
};

export type ConfirmResponse = {
  session_id: string;
  fingerprint: string;
  selection_method: "auto" | "human";
  score: number;
  cid: string;
  tx_hash: string;
  explorer_link: string;
};

export type OnChainRecord = {
  exists: boolean;
  submitter: string;
  timestamp: number;
  uri: string;
};

export type VerifyResponse = {
  passed: boolean;
  fingerprint: string;
  fetched_fingerprint: string | null;
  on_chain_record: OnChainRecord;
  message: string;
};
