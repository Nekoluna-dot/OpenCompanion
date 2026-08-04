use std::collections::HashMap;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LedgerEvent {
    pub seq: u64,
    pub event_type: String,
    pub trace_id: String,
    pub trace_kind: String,
    pub body_hash: String,
    pub payload: EventPayload,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EventPayload {
    pub resolved: Option<bool>,
    pub activation_count: Option<u64>,
    pub tombstone: bool,
    pub erasure_mode: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReplayReport {
    pub ok: bool,
    pub event_count: usize,
    pub latest_seq: u64,
    pub projection_trace_count: usize,
    pub tombstone_count: usize,
    pub unknown_event_count: usize,
    pub violations: Vec<ReplayFailure>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReplayFailure {
    pub code: ViolationCode,
    pub seq: Option<u64>,
    pub trace_id: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ViolationCode {
    NonIncreasingSeq,
    MissingTraceId,
    InvalidBodyHash,
    TombstoneNotDeleted,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
struct TraceState {
    deleted: bool,
    tombstone: bool,
}

#[derive(Clone, Debug, Default)]
pub struct ReplayKernel;

impl ReplayKernel {
    pub fn new() -> Self {
        Self
    }

    pub fn validate(&self, events: &[LedgerEvent]) -> ReplayReport {
        let mut violations = Vec::new();
        let mut traces: HashMap<String, TraceState> = HashMap::new();
        let mut latest_seq = 0_u64;
        let mut previous_seq = 0_u64;
        let mut unknown_event_count = 0_usize;

        for event in events {
            if event.seq <= previous_seq {
                violations.push(ReplayFailure {
                    code: ViolationCode::NonIncreasingSeq,
                    seq: Some(event.seq),
                    trace_id: Some(event.trace_id.clone()),
                });
            }
            previous_seq = event.seq;
            latest_seq = latest_seq.max(event.seq);

            if event.trace_id.trim().is_empty() {
                violations.push(ReplayFailure {
                    code: ViolationCode::MissingTraceId,
                    seq: Some(event.seq),
                    trace_id: None,
                });
            }

            if !is_valid_body_hash(&event.body_hash) {
                violations.push(ReplayFailure {
                    code: ViolationCode::InvalidBodyHash,
                    seq: Some(event.seq),
                    trace_id: Some(event.trace_id.clone()),
                });
            }

            if !is_known_event(&event.event_type) {
                unknown_event_count += 1;
                continue;
            }

            if event.trace_id.trim().is_empty() {
                continue;
            }
            let trace = traces.entry(event.trace_id.clone()).or_default();
            if event.event_type == "TraceDeletedToArchive" {
                trace.deleted = true;
            }
            if is_tombstone_event(event) {
                trace.tombstone = true;
            }
        }

        for (trace_id, trace) in &traces {
            if trace.tombstone && !trace.deleted {
                violations.push(ReplayFailure {
                    code: ViolationCode::TombstoneNotDeleted,
                    seq: None,
                    trace_id: Some(trace_id.clone()),
                });
            }
        }

        let tombstone_count = traces.values().filter(|trace| trace.tombstone).count();
        ReplayReport {
            ok: violations.is_empty(),
            event_count: events.len(),
            latest_seq,
            projection_trace_count: traces.len(),
            tombstone_count,
            unknown_event_count,
            violations,
        }
    }
}

fn is_known_event(event_type: &str) -> bool {
    matches!(
        event_type,
        "TraceCreated" | "TraceUpdated" | "TraceTouched" | "TraceArchived" | "TraceDeletedToArchive"
    )
}

fn is_tombstone_event(event: &LedgerEvent) -> bool {
    event.payload.tombstone
        || event
            .payload
            .erasure_mode
            .as_deref()
            .map(|mode| mode.eq_ignore_ascii_case("tombstone_only"))
            .unwrap_or(false)
}

fn is_valid_body_hash(value: &str) -> bool {
    let Some(hex) = value.strip_prefix("sha256:") else {
        return false;
    };
    hex.len() == 64 && hex.bytes().all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn event(seq: u64, event_type: &str, trace_id: &str) -> LedgerEvent {
        LedgerEvent {
            seq,
            event_type: event_type.to_string(),
            trace_id: trace_id.to_string(),
            trace_kind: "dynamic".to_string(),
            body_hash: format!("sha256:{:064x}", seq),
            payload: EventPayload::default(),
        }
    }

    #[test]
    fn accepts_valid_tombstone_lifecycle() {
        let mut deleted = event(3, "TraceDeletedToArchive", "b1");
        deleted.payload.tombstone = true;
        deleted.payload.erasure_mode = Some("tombstone_only".to_string());
        let events = vec![
            event(1, "TraceCreated", "b1"),
            event(2, "TraceTouched", "b1"),
            deleted,
        ];

        let report = ReplayKernel::new().validate(&events);

        assert!(report.ok);
        assert_eq!(report.event_count, 3);
        assert_eq!(report.latest_seq, 3);
        assert_eq!(report.projection_trace_count, 1);
        assert_eq!(report.tombstone_count, 1);
        assert!(report.violations.is_empty());
    }

    #[test]
    fn reports_structural_violations() {
        let mut bad = event(1, "TraceUpdated", "b1");
        bad.body_hash = "not-a-sha".to_string();
        let events = vec![event(1, "TraceCreated", "b1"), bad, event(2, "TraceTouched", "")];

        let report = ReplayKernel::new().validate(&events);
        let codes: Vec<ViolationCode> = report
            .violations
            .iter()
            .map(|failure| failure.code.clone())
            .collect();

        assert!(!report.ok);
        assert!(codes.contains(&ViolationCode::NonIncreasingSeq));
        assert!(codes.contains(&ViolationCode::InvalidBodyHash));
        assert!(codes.contains(&ViolationCode::MissingTraceId));
    }
}
