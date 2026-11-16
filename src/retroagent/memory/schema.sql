-- RetroAgent project memory, schema version 1. Source: spec/data-model.md.
-- Applied once to a new database by retroagent.memory.migrations.
-- Conventions: timestamps are ISO 8601 UTC text, lists are JSON arrays as text, booleans are 0 or 1.

-- Sessions and audit ---------------------------------------------------------------------------

CREATE TABLE schema_info (
    "key"   TEXT PRIMARY KEY,
    "value" TEXT NOT NULL
);

CREATE TABLE session (
    id                INTEGER PRIMARY KEY,
    started_at        TEXT NOT NULL,
    ended_at          TEXT,
    model             TEXT NOT NULL,
    interactive       INTEGER NOT NULL CHECK (interactive IN (0, 1)),
    base_ref          TEXT,
    base_commit       TEXT,
    candidate_ref     TEXT,
    candidate_commit  TEXT,
    result_char_limit INTEGER NOT NULL
);

CREATE TABLE tool_call (
    id         INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES session (id),
    server     TEXT NOT NULL,
    tool       TEXT NOT NULL,
    arguments  TEXT NOT NULL,
    outcome    TEXT NOT NULL CHECK (outcome IN ('ok', 'error', 'denied')),
    error      TEXT,
    started_at TEXT NOT NULL,
    ended_at   TEXT
);

-- Requirements ---------------------------------------------------------------------------------

CREATE TABLE requirement (
    id          TEXT PRIMARY KEY CHECK (id GLOB 'REQ-[0-9][0-9][0-9]*'),
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    priority    TEXT CHECK (priority IN ('high', 'medium', 'low')),
    since       TEXT,
    removed     TEXT,
    source_file TEXT NOT NULL,
    synced_at   TEXT NOT NULL
);

CREATE TABLE requirement_change (
    requirement_id TEXT NOT NULL REFERENCES requirement (id),
    version        TEXT NOT NULL,
    description    TEXT NOT NULL
);

-- Impact analysis ------------------------------------------------------------------------------

CREATE TABLE analysis (
    id               INTEGER PRIMARY KEY,
    base_ref         TEXT NOT NULL,
    base_commit      TEXT NOT NULL,
    candidate_ref    TEXT NOT NULL,
    candidate_commit TEXT NOT NULL,
    session_id       INTEGER NOT NULL REFERENCES session (id),
    created_at       TEXT NOT NULL
);

CREATE TABLE analysis_file (
    analysis_id   INTEGER NOT NULL REFERENCES analysis (id),
    path          TEXT NOT NULL,
    old_path      TEXT,
    change        TEXT NOT NULL CHECK (change IN ('added', 'modified', 'deleted', 'renamed')),
    lines_added   INTEGER NOT NULL,
    lines_removed INTEGER NOT NULL,
    PRIMARY KEY (analysis_id, path)
);

CREATE TABLE analysis_module (
    analysis_id INTEGER NOT NULL REFERENCES analysis (id),
    module      TEXT NOT NULL,
    files       TEXT NOT NULL CHECK (CASE WHEN json_valid(files) THEN json_type(files) = 'array' ELSE 0 END),
    risk_level  TEXT NOT NULL CHECK (risk_level IN ('high', 'medium', 'low')),
    reason      TEXT NOT NULL,
    PRIMARY KEY (analysis_id, module)
);

CREATE TABLE analysis_requirement (
    analysis_id    INTEGER NOT NULL REFERENCES analysis (id),
    requirement_id TEXT NOT NULL REFERENCES requirement (id),
    reason         TEXT NOT NULL,
    PRIMARY KEY (analysis_id, requirement_id)
);

CREATE TABLE risk (
    id          TEXT PRIMARY KEY CHECK (id GLOB 'RSK-[0-9][0-9][0-9]*'),
    description TEXT NOT NULL,
    level       TEXT NOT NULL CHECK (level IN ('high', 'medium', 'low')),
    analysis_id INTEGER NOT NULL REFERENCES analysis (id),
    created_at  TEXT NOT NULL
);

CREATE TABLE risk_requirement (
    risk_id        TEXT NOT NULL REFERENCES risk (id),
    requirement_id TEXT NOT NULL REFERENCES requirement (id),
    PRIMARY KEY (risk_id, requirement_id)
);

-- Test design and selection --------------------------------------------------------------------

CREATE TABLE test_case (
    id              TEXT PRIMARY KEY CHECK (id GLOB 'TC-[0-9][0-9][0-9]*'),
    title           TEXT NOT NULL,
    objective       TEXT,
    priority        TEXT NOT NULL CHECK (priority IN ('high', 'medium', 'low')),
    status          TEXT NOT NULL CHECK (status IN ('designed', 'implemented')),
    origin          TEXT NOT NULL CHECK (origin IN ('designed', 'project_suite')),
    designed_by     TEXT,
    preconditions   TEXT NOT NULL DEFAULT '[]'
                    CHECK (CASE WHEN json_valid(preconditions) THEN json_type(preconditions) = 'array' ELSE 0 END),
    input_data      TEXT NOT NULL DEFAULT '[]'
                    CHECK (CASE WHEN json_valid(input_data) THEN json_type(input_data) = 'array' ELSE 0 END),
    steps           TEXT NOT NULL DEFAULT '[]'
                    CHECK (CASE WHEN json_valid(steps) THEN json_type(steps) = 'array' ELSE 0 END),
    expected_result TEXT,
    test_id         TEXT UNIQUE,
    implementation  TEXT,
    revision        INTEGER,
    retired_at      TEXT,
    retire_reason   TEXT,
    retired_by      TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    -- INV-05
    CHECK (
        (status = 'implemented' AND implementation IS NOT NULL)
        OR (status = 'designed' AND implementation IS NULL AND test_id IS NULL AND revision IS NULL)
    )
);

CREATE TABLE test_case_requirement (
    test_case_id   TEXT NOT NULL REFERENCES test_case (id),
    requirement_id TEXT NOT NULL REFERENCES requirement (id),
    link           TEXT NOT NULL CHECK (link IN ('design', 'name')),
    PRIMARY KEY (test_case_id, requirement_id, link)
);

CREATE TABLE suite (
    id          INTEGER PRIMARY KEY,
    analysis_id INTEGER NOT NULL REFERENCES analysis (id),
    session_id  INTEGER NOT NULL REFERENCES session (id),
    created_at  TEXT NOT NULL
);

CREATE TABLE suite_test_case (
    suite_id         INTEGER NOT NULL REFERENCES suite (id),
    test_case_id     TEXT NOT NULL REFERENCES test_case (id),
    position         INTEGER NOT NULL,
    selection_reason TEXT NOT NULL,
    PRIMARY KEY (suite_id, test_case_id)
);

-- Execution ------------------------------------------------------------------------------------

CREATE TABLE run (
    id           TEXT PRIMARY KEY CHECK (id GLOB 'RUN-[0-9][0-9][0-9][0-9]*'),
    version_role TEXT NOT NULL CHECK (version_role IN ('base', 'candidate')),
    ref          TEXT NOT NULL,
    "commit"     TEXT NOT NULL,
    scope        TEXT NOT NULL CHECK (scope IN ('suite', 'all', 'selected')),
    suite_id     INTEGER REFERENCES suite (id),
    status       TEXT NOT NULL CHECK (status IN ('running', 'completed', 'error', 'interrupted')),
    command      TEXT NOT NULL,
    exit_code    INTEGER,
    junit_path   TEXT,
    evidence_dir TEXT NOT NULL,
    error        TEXT,
    session_id   INTEGER NOT NULL REFERENCES session (id),
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    -- INV-09
    CHECK (scope <> 'suite' OR suite_id IS NOT NULL)
);

CREATE TABLE test_execution (
    id            INTEGER PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES run (id),
    test_case_id  TEXT NOT NULL REFERENCES test_case (id),
    status        TEXT NOT NULL CHECK (status IN ('executed', 'blocked', 'skipped')),
    result        TEXT CHECK (result IN ('passed', 'failed', 'error')),
    reason        TEXT,
    duration      REAL,
    test_revision INTEGER,
    UNIQUE (run_id, test_case_id),
    -- INV-01
    CHECK ((status = 'executed') = (result IS NOT NULL)),
    CHECK (
        status <> 'blocked'
        OR reason IN ('setup_failed', 'service_not_ready', 'no_junit', 'not_reported', 'timeout', 'interrupted')
    )
);

CREATE TABLE attempt (
    execution_id    INTEGER NOT NULL REFERENCES test_execution (id),
    number          INTEGER NOT NULL CHECK (number >= 1),
    result          TEXT NOT NULL CHECK (result IN ('passed', 'failed', 'error')),
    duration        REAL,
    failure_message TEXT,
    PRIMARY KEY (execution_id, number)
);

-- Interpretation -------------------------------------------------------------------------------

CREATE TABLE triage (
    id             INTEGER PRIMARY KEY,
    execution_id   INTEGER NOT NULL REFERENCES test_execution (id),
    classification TEXT NOT NULL
                   CHECK (classification IN
                          ('regression', 'expected_change', 'flaky', 'environment', 'test_defect', 'pre_existing')),
    justification  TEXT NOT NULL,
    triaged_by     TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE defect (
    id              TEXT PRIMARY KEY CHECK (id GLOB 'DEF-[0-9][0-9][0-9]*'),
    title           TEXT NOT NULL,
    severity        TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    detected_run_id TEXT NOT NULL REFERENCES run (id),
    detected_at     TEXT NOT NULL,
    expected        TEXT,
    actual          TEXT NOT NULL,
    steps           TEXT NOT NULL DEFAULT '[]'
                    CHECK (CASE WHEN json_valid(steps) THEN json_type(steps) = 'array' ELSE 0 END),
    closed_at       TEXT,
    closed_by       TEXT CHECK (closed_by IN ('run', 'user')),
    closed_run_id   TEXT REFERENCES run (id),
    close_reason    TEXT,
    -- INV-12
    CHECK (
        (status = 'open'
            AND closed_at IS NULL AND closed_by IS NULL AND close_reason IS NULL AND closed_run_id IS NULL)
        OR (status = 'closed'
            AND closed_at IS NOT NULL AND closed_by IS NOT NULL AND close_reason IS NOT NULL
            AND (closed_by <> 'run' OR closed_run_id IS NOT NULL))
    )
);

CREATE TABLE defect_execution (
    defect_id    TEXT NOT NULL REFERENCES defect (id),
    execution_id INTEGER NOT NULL REFERENCES test_execution (id),
    PRIMARY KEY (defect_id, execution_id)
);

-- Reporting ------------------------------------------------------------------------------------

CREATE TABLE evaluation (
    id                    INTEGER PRIMARY KEY,
    run_id                TEXT NOT NULL REFERENCES run (id),
    baseline_run_id       TEXT REFERENCES run (id),
    full_base_run_id      TEXT REFERENCES run (id),
    full_candidate_run_id TEXT REFERENCES run (id),
    analysis_id           INTEGER REFERENCES analysis (id),
    thresholds            TEXT NOT NULL CHECK (json_valid(thresholds)),
    metrics               TEXT NOT NULL CHECK (json_valid(metrics)),
    criteria              TEXT NOT NULL CHECK (json_valid(criteria)),
    decision              TEXT NOT NULL CHECK (decision IN ('release', 'release_with_conditions', 'do_not_release')),
    decision_details      TEXT NOT NULL CHECK (json_valid(decision_details)),
    tool_version          TEXT NOT NULL,
    created_at            TEXT NOT NULL
);

CREATE TABLE report (
    id            TEXT PRIMARY KEY CHECK (id GLOB 'RPT-[0-9][0-9][0-9][0-9]*'),
    type          TEXT NOT NULL CHECK (type IN ('test-plan', 'test-cases', 'status', 'defects', 'completion')),
    status        TEXT NOT NULL CHECK (status IN ('draft', 'rendered')),
    evaluation_id INTEGER REFERENCES evaluation (id),
    model         TEXT NOT NULL,
    path          TEXT NOT NULL,
    formats       TEXT NOT NULL CHECK (CASE WHEN json_valid(formats) THEN json_type(formats) = 'array' ELSE 0 END),
    created_at    TEXT NOT NULL
);

-- Triggers -------------------------------------------------------------------------------------

-- INV-02: an executed test execution needs a run with stored JUnit XML.
CREATE TRIGGER inv_02_executed_needs_junit
BEFORE INSERT ON test_execution
WHEN NEW.status = 'executed' AND (SELECT junit_path FROM run WHERE id = NEW.run_id) IS NULL
BEGIN
    SELECT RAISE(ABORT, 'INV-02: an executed test execution needs a run with a stored JUnit XML');
END;

-- INV-06: a designed test case has no test executions.
CREATE TRIGGER inv_06_designed_has_no_executions
BEFORE INSERT ON test_execution
WHEN (SELECT status FROM test_case WHERE id = NEW.test_case_id) = 'designed'
BEGIN
    SELECT RAISE(ABORT, 'INV-06: a designed test case has no test executions');
END;

-- INV-09: the executions of a suite run are only for test cases of that suite.
CREATE TRIGGER inv_09_suite_run_executions
BEFORE INSERT ON test_execution
WHEN (SELECT scope FROM run WHERE id = NEW.run_id) = 'suite'
 AND NOT EXISTS (SELECT 1
                 FROM run
                 JOIN suite_test_case AS s ON s.suite_id = run.suite_id
                 WHERE run.id = NEW.run_id AND s.test_case_id = NEW.test_case_id)
BEGIN
    SELECT RAISE(ABORT, 'INV-09: the test case is not in the suite of the run');
END;

-- INV-04: the first attempt gives the result; later attempts exist only when it did not pass.
CREATE TRIGGER inv_04_attempt_of_executed
BEFORE INSERT ON attempt
WHEN (SELECT status FROM test_execution WHERE id = NEW.execution_id) IS NOT 'executed'
BEGIN
    SELECT RAISE(ABORT, 'INV-04: only an executed test execution has attempts');
END;

CREATE TRIGGER inv_04_first_attempt_is_the_result
BEFORE INSERT ON attempt
WHEN NEW.number = 1
 AND NEW.result IS NOT (SELECT result FROM test_execution WHERE id = NEW.execution_id)
BEGIN
    SELECT RAISE(ABORT, 'INV-04: the result of a test execution is the result of its first attempt');
END;

CREATE TRIGGER inv_04_rerun_only_after_failure
BEFORE INSERT ON attempt
WHEN NEW.number > 1
 AND COALESCE((SELECT result FROM attempt WHERE execution_id = NEW.execution_id AND number = 1), 'passed') = 'passed'
BEGIN
    SELECT RAISE(ABORT, 'INV-04: later attempts exist only when the first attempt did not pass');
END;

-- INV-08: a triage and a defect link refer only to failed or error executions.
CREATE TRIGGER inv_08_triage_of_failure
BEFORE INSERT ON triage
WHEN COALESCE((SELECT result FROM test_execution WHERE id = NEW.execution_id), '') NOT IN ('failed', 'error')
BEGIN
    SELECT RAISE(ABORT, 'INV-08: a triage refers only to an execution with result failed or error');
END;

CREATE TRIGGER inv_08_defect_link_to_failure
BEFORE INSERT ON defect_execution
WHEN COALESCE((SELECT result FROM test_execution WHERE id = NEW.execution_id), '') NOT IN ('failed', 'error')
BEGIN
    SELECT RAISE(ABORT, 'INV-08: a defect links only to an execution with result failed or error');
END;

-- INV-10: records that are complete are never updated.
CREATE TRIGGER inv_10_run_is_final
BEFORE UPDATE ON run
WHEN OLD.status <> 'running'
BEGIN
    SELECT RAISE(ABORT, 'INV-10: a run that is not running is never updated');
END;

CREATE TRIGGER inv_10_test_execution_is_final
BEFORE UPDATE ON test_execution
BEGIN
    SELECT RAISE(ABORT, 'INV-10: a test execution is never updated');
END;

CREATE TRIGGER inv_10_attempt_is_final
BEFORE UPDATE ON attempt
BEGIN
    SELECT RAISE(ABORT, 'INV-10: an attempt is never updated');
END;

CREATE TRIGGER inv_10_triage_is_final
BEFORE UPDATE ON triage
BEGIN
    SELECT RAISE(ABORT, 'INV-10: a triage is never updated');
END;

CREATE TRIGGER inv_10_analysis_module_is_final
BEFORE UPDATE ON analysis_module
BEGIN
    SELECT RAISE(ABORT, 'INV-10: the impact of an analysis is never updated');
END;

CREATE TRIGGER inv_10_analysis_requirement_is_final
BEFORE UPDATE ON analysis_requirement
BEGIN
    SELECT RAISE(ABORT, 'INV-10: the impact of an analysis is never updated');
END;

CREATE TRIGGER inv_10_evaluation_is_final
BEFORE UPDATE ON evaluation
BEGIN
    SELECT RAISE(ABORT, 'INV-10: an evaluation is never updated');
END;

CREATE TRIGGER inv_10_rendered_report_is_final
BEFORE UPDATE ON report
WHEN OLD.status = 'rendered'
BEGIN
    SELECT RAISE(ABORT, 'INV-10: a rendered report is never updated');
END;

-- INV-10: no execution or attempt is added to a run that is not running.
CREATE TRIGGER inv_10_execution_needs_running_run
BEFORE INSERT ON test_execution
WHEN (SELECT status FROM run WHERE id = NEW.run_id) <> 'running'
BEGIN
    SELECT RAISE(ABORT, 'INV-10: no execution is added to a run that is not running');
END;

CREATE TRIGGER inv_10_attempt_needs_running_run
BEFORE INSERT ON attempt
WHEN (SELECT r.status FROM test_execution e JOIN run r ON r.id = e.run_id WHERE e.id = NEW.execution_id) <> 'running'
BEGIN
    SELECT RAISE(ABORT, 'INV-10: no attempt is added to a run that is not running');
END;

-- INV-11: records are never deleted.
CREATE TRIGGER inv_11_schema_info BEFORE DELETE ON schema_info
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_session BEFORE DELETE ON session
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_tool_call BEFORE DELETE ON tool_call
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_requirement BEFORE DELETE ON requirement
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_requirement_change BEFORE DELETE ON requirement_change
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_analysis BEFORE DELETE ON analysis
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_analysis_file BEFORE DELETE ON analysis_file
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_analysis_module BEFORE DELETE ON analysis_module
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_analysis_requirement BEFORE DELETE ON analysis_requirement
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_risk BEFORE DELETE ON risk
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_risk_requirement BEFORE DELETE ON risk_requirement
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_test_case BEFORE DELETE ON test_case
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
-- The one exception: design links are replaced when the requirement_ids of a test case change. Name links stay.
CREATE TRIGGER inv_11_test_case_requirement BEFORE DELETE ON test_case_requirement
WHEN OLD.link <> 'design'
BEGIN SELECT RAISE(ABORT, 'INV-11: links found in a test name are never deleted'); END;
CREATE TRIGGER inv_11_suite BEFORE DELETE ON suite
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_suite_test_case BEFORE DELETE ON suite_test_case
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_run BEFORE DELETE ON run
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_test_execution BEFORE DELETE ON test_execution
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_attempt BEFORE DELETE ON attempt
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_triage BEFORE DELETE ON triage
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_defect BEFORE DELETE ON defect
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_defect_execution BEFORE DELETE ON defect_execution
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_evaluation BEFORE DELETE ON evaluation
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
CREATE TRIGGER inv_11_report BEFORE DELETE ON report
BEGIN SELECT RAISE(ABORT, 'INV-11: records are never deleted'); END;
