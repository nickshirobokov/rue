"""Turso schema for Rue suite storage."""

SCHEMA_VERSION = 2
TURSO_FEATURES = "custom_types,index_method"

REQUIRED_CUSTOM_TYPES = frozenset(
    {
        "boolean",
        "json",
        "jsonb",
        "timestamp",
        "uuid",
        "varchar",
    }
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS rue_schema (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    version     INTEGER NOT NULL,
    features    TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS suite_executions (
    suite_execution_id              uuid PRIMARY KEY,
    start_time          timestamp NOT NULL,
    end_time            timestamp,
    total_duration_ms   REAL NOT NULL DEFAULT 0,

    passed              INTEGER NOT NULL DEFAULT 0,
    failed              INTEGER NOT NULL DEFAULT 0,
    errors              INTEGER NOT NULL DEFAULT 0,
    skipped             INTEGER NOT NULL DEFAULT 0,
    xfailed             INTEGER NOT NULL DEFAULT 0,
    xpassed             INTEGER NOT NULL DEFAULT 0,
    total               INTEGER NOT NULL DEFAULT 0,
    stopped_early       boolean NOT NULL DEFAULT 0,

    commit_hash         varchar(64),
    branch              TEXT,
    dirty               boolean,
    python_version      varchar(32) NOT NULL,
    platform            TEXT NOT NULL,
    hostname            TEXT NOT NULL,
    working_directory   TEXT NOT NULL,
    rue_version         varchar(64) NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS test_executions (
    test_execution_id   uuid PRIMARY KEY,
    suite_execution_id  uuid NOT NULL
        REFERENCES suite_executions(suite_execution_id) ON DELETE CASCADE,
    parent_id           uuid
        REFERENCES test_executions(test_execution_id) ON DELETE CASCADE,

    function_name       varchar(256) NOT NULL,
    module_path         TEXT NOT NULL,
    class_name          varchar(256),
    is_async            boolean NOT NULL,
    case_id             uuid,
    suffix              TEXT,
    collection_index    INTEGER NOT NULL,
    skip_reason         TEXT,
    xfail_reason        TEXT,
    xfail_strict        boolean NOT NULL,

    status              varchar(16) NOT NULL,
    duration_ms         REAL NOT NULL,
    error_type          varchar(256),
    error_message       TEXT,
    error_traceback     jsonb
) STRICT;

CREATE INDEX IF NOT EXISTS idx_test_executions_suite ON test_executions(suite_execution_id);
CREATE INDEX IF NOT EXISTS idx_test_executions_parent ON test_executions(parent_id);
CREATE INDEX IF NOT EXISTS idx_test_executions_name ON test_executions(function_name);
CREATE INDEX IF NOT EXISTS idx_test_executions_status ON test_executions(status);

CREATE TABLE IF NOT EXISTS test_execution_tags (
    test_execution_id   uuid NOT NULL
        REFERENCES test_executions(test_execution_id) ON DELETE CASCADE,
    tag                 varchar(128) NOT NULL,
    PRIMARY KEY (test_execution_id, tag)
) STRICT;

CREATE TABLE IF NOT EXISTS metrics (
    metric_id           INTEGER PRIMARY KEY,
    suite_execution_id  uuid NOT NULL
        REFERENCES suite_executions(suite_execution_id) ON DELETE CASCADE,

    name                varchar(256) NOT NULL,
    scope               varchar(32) NOT NULL,
    provider_path       TEXT NOT NULL,

    value_integer       INTEGER,
    value_real          REAL,
    value_boolean       boolean,
    value_json          jsonb,

    first_recorded_at   timestamp,
    last_recorded_at    timestamp
) STRICT;

CREATE INDEX IF NOT EXISTS idx_metrics_suite ON metrics(suite_execution_id);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(name);

CREATE TABLE IF NOT EXISTS metric_consumers (
    id                  INTEGER PRIMARY KEY,
    metric_id           INTEGER NOT NULL
        REFERENCES metrics(metric_id) ON DELETE CASCADE,
    kind                varchar(16) NOT NULL,
    function_name       varchar(256) NOT NULL,
    module_path         TEXT NOT NULL,
    class_name          varchar(256),
    scope               varchar(32),
    suffix              TEXT,
    case_id             uuid
) STRICT;

CREATE INDEX IF NOT EXISTS idx_metric_consumers_metric
ON metric_consumers(metric_id);

CREATE TABLE IF NOT EXISTS metric_dependencies (
    id                  INTEGER PRIMARY KEY,
    metric_id           INTEGER NOT NULL
        REFERENCES metrics(metric_id) ON DELETE CASCADE,
    function_name       varchar(256) NOT NULL,
    module_path         TEXT NOT NULL,
    scope               varchar(32) NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_metric_dependencies_metric
ON metric_dependencies(metric_id);

CREATE TABLE IF NOT EXISTS assertions (
    assertion_id        INTEGER PRIMARY KEY,
    suite_execution_id  uuid NOT NULL
        REFERENCES suite_executions(suite_execution_id) ON DELETE CASCADE,
    test_execution_id   uuid
        REFERENCES test_executions(test_execution_id) ON DELETE CASCADE,
    metric_id           INTEGER
        REFERENCES metrics(metric_id) ON DELETE SET NULL,

    expression          TEXT NOT NULL,
    lines_above         TEXT NOT NULL,
    lines_below         TEXT NOT NULL,
    resolved_args       jsonb NOT NULL,
    col_offset          INTEGER NOT NULL,
    passed              boolean NOT NULL,
    error_message       TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_assertions_suite ON assertions(suite_execution_id);
CREATE INDEX IF NOT EXISTS idx_assertions_test_execution
ON assertions(test_execution_id);
CREATE INDEX IF NOT EXISTS idx_assertions_metric ON assertions(metric_id);

CREATE TABLE IF NOT EXISTS predicates (
    predicate_id        INTEGER PRIMARY KEY,
    suite_execution_id  uuid NOT NULL
        REFERENCES suite_executions(suite_execution_id) ON DELETE CASCADE,
    assertion_id        INTEGER NOT NULL
        REFERENCES assertions(assertion_id) ON DELETE CASCADE,

    predicate_name      varchar(256) NOT NULL,
    actual              TEXT NOT NULL,
    reference           TEXT NOT NULL,
    strict              boolean NOT NULL,
    confidence          REAL NOT NULL,
    value               boolean NOT NULL,
    message             TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_predicates_assertion ON predicates(assertion_id);
CREATE INDEX IF NOT EXISTS idx_predicates_suite ON predicates(suite_execution_id);
CREATE INDEX IF NOT EXISTS idx_predicates_name ON predicates(predicate_name);
"""
