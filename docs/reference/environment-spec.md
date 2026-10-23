# Environment spec

!!! note
    Auto-generated from `agentlab.environment` (pydantic models); do not edit. Run `uv run python scripts/gen_reference.py`.


An environment is a YAML file in `environments/`: tables plus SQL-backed tools. Identifiers match `[a-z][a-z0-9_]{0,47}`; the environment `id` matches `[a-z0-9][a-z0-9._-]{0,63}`.

## Models

### EnvironmentSpec

A versioned environment: the tables and tools of one simulated world.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `id` | `str` | yes |  | Environment id: 1-64 lowercase letters, digits, `.`, `_` or `-`. |
| `version` | `int` | yes |  | Bumped whenever the spec changes; scenarios pin `id@version`. (>= 1) |
| `description` | `str` | yes |  | The world in plain English; also given to agents as context. |
| `tables` | `list[Table]` | yes |  | Tables created for every trial; names are unique. (min length 1) |
| `tools` | `list[ToolSpec]` | yes |  | Tools the agent can call; names are unique. (min length 1) |

### Table

A table created in the trial's private Postgres schema.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | `str` | yes |  | Table name: lowercase letters, digits and `_`; `ledger` and `idempotency` are reserved. |
| `columns` | `list[Column]` | yes |  | Columns, in order; at least one. (min length 1) |

### Column

One column of an environment table.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | `str` | yes |  | Column name: lowercase letters, digits and `_`, starting with a letter (max 48). |
| `type` | `"text" \| "integer" \| "bigint" \| "numeric" \| "boolean" \| "timestamptz" \| "jsonb"` | yes |  | Postgres type the column is created with. |
| `primary_key` | `bool` | no | `false` | Part of the table's primary key (several columns make a composite key). |
| `nullable` | `bool` | no | `true` | Whether NULL values are allowed. |
| `unique` | `bool` | no | `false` | Values must be distinct across rows. |
| `serial` | `bool` | no | `false` | Auto-incrementing integer key. Deterministic, so ledger replay reproduces the same ids. |
| `references` | `str \| null` | no | `null` | Foreign key target as `"table.column"`, e.g. `"customers.id"`. |

### ToolSpec

One tool: typed parameters, optional rules, then ONE SQL statement (parameters bound as %(name)s; use
RETURNING to send rows back). Runs as the trial's writer role: it can change this environment's tables only.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | `str` | yes |  | Tool name the agent calls; lowercase letters, digits and `_`. |
| `description` | `str` | yes |  | What the tool does, shown to the agent in the tool catalog. |
| `params` | `list[ToolParam]` | no | `[]` | Typed arguments the tool accepts. |
| `rules` | `list[Rule]` | no | `[]` | Preconditions checked in order before the SQL runs. |
| `sql` | `str` | yes |  | The single SQL statement to run; add RETURNING to send rows back. |
| `returns` | `"row" \| "rows" \| "none"` | no | `"row"` | Response shape: `row` is the first row (404 when none), `rows` is a list, `none` is `{}`. |
| `success_status` | `int` | no | `200` | HTTP status returned on success. (>= 200, <= 299) |
| `idempotent` | `bool` | no | `false` | Adds an `idempotency_key` argument; a repeated key replays the first response without re-running. |
| `mutates` | `bool` | no | `true` | False for read-only tools; they are still recorded in the ledger but never committed. |

### ToolParam

One typed argument of a tool.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | `str` | yes |  | Parameter name; bound into the tool's SQL as `%(name)s`. |
| `type` | `"string" \| "integer" \| "number" \| "boolean"` | yes |  | JSON type the agent must supply. |
| `description` | `str` | no | `""` | Shown to the agent in the tool catalog. |
| `required` | `bool` | no | `true` | Calls without this argument are rejected (422). |
| `enum` | `list[str] \| null` | no | `null` | Allowed values, compared as strings; omit for any value. |

### Rule

A precondition evaluated before the effect. `sql` is one SELECT returning a single boolean cell, with the
tool's parameters bound as %(name)s. When it returns true the call fails with `status` and `error` and has no
side effect (e.g. "insufficient seats" -> 409).

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `sql` | `str` | yes |  | One SELECT returning a single boolean; true means the call must be refused. |
| `status` | `int` | yes |  | HTTP status returned to the agent when the rule fires. (>= 400, <= 499) |
| `error` | `str` | yes |  | Message returned to the agent when the rule fires. |

## JSON Schema

??? abstract "EnvironmentSpec JSON Schema"

    ```json
    {
      "$defs": {
        "Column": {
          "description": "One column of an environment table.",
          "properties": {
            "name": {
              "description": "Column name: lowercase letters, digits and `_`, starting with a letter (max 48).",
              "title": "Name",
              "type": "string"
            },
            "nullable": {
              "default": true,
              "description": "Whether NULL values are allowed.",
              "title": "Nullable",
              "type": "boolean"
            },
            "primary_key": {
              "default": false,
              "description": "Part of the table's primary key (several columns make a composite key).",
              "title": "Primary Key",
              "type": "boolean"
            },
            "references": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "description": "Foreign key target as `\"table.column\"`, e.g. `\"customers.id\"`.",
              "title": "References"
            },
            "serial": {
              "default": false,
              "description": "Auto-incrementing integer key. Deterministic, so ledger replay reproduces the same ids.",
              "title": "Serial",
              "type": "boolean"
            },
            "type": {
              "$ref": "#/$defs/ColumnType",
              "description": "Postgres type the column is created with."
            },
            "unique": {
              "default": false,
              "description": "Values must be distinct across rows.",
              "title": "Unique",
              "type": "boolean"
            }
          },
          "required": [
            "name",
            "type"
          ],
          "title": "Column",
          "type": "object"
        },
        "ColumnType": {
          "enum": [
            "text",
            "integer",
            "bigint",
            "numeric",
            "boolean",
            "timestamptz",
            "jsonb"
          ],
          "type": "string"
        },
        "ParamType": {
          "enum": [
            "string",
            "integer",
            "number",
            "boolean"
          ],
          "type": "string"
        },
        "Rule": {
          "description": "A precondition evaluated before the effect. `sql` is one SELECT returning a single boolean cell, with the\ntool's parameters bound as %(name)s. When it returns true the call fails with `status` and `error` and has no\nside effect (e.g. \"insufficient seats\" -> 409).",
          "properties": {
            "error": {
              "description": "Message returned to the agent when the rule fires.",
              "title": "Error",
              "type": "string"
            },
            "sql": {
              "description": "One SELECT returning a single boolean; true means the call must be refused.",
              "title": "Sql",
              "type": "string"
            },
            "status": {
              "description": "HTTP status returned to the agent when the rule fires.",
              "maximum": 499,
              "minimum": 400,
              "title": "Status",
              "type": "integer"
            }
          },
          "required": [
            "sql",
            "status",
            "error"
          ],
          "title": "Rule",
          "type": "object"
        },
        "Table": {
          "description": "A table created in the trial's private Postgres schema.",
          "properties": {
            "columns": {
              "description": "Columns, in order; at least one.",
              "items": {
                "$ref": "#/$defs/Column"
              },
              "minItems": 1,
              "title": "Columns",
              "type": "array"
            },
            "name": {
              "description": "Table name: lowercase letters, digits and `_`; `ledger` and `idempotency` are reserved.",
              "title": "Name",
              "type": "string"
            }
          },
          "required": [
            "name",
            "columns"
          ],
          "title": "Table",
          "type": "object"
        },
        "ToolParam": {
          "description": "One typed argument of a tool.",
          "properties": {
            "description": {
              "default": "",
              "description": "Shown to the agent in the tool catalog.",
              "title": "Description",
              "type": "string"
            },
            "enum": {
              "anyOf": [
                {
                  "items": {
                    "type": "string"
                  },
                  "type": "array"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "description": "Allowed values, compared as strings; omit for any value.",
              "title": "Enum"
            },
            "name": {
              "description": "Parameter name; bound into the tool's SQL as `%(name)s`.",
              "title": "Name",
              "type": "string"
            },
            "required": {
              "default": true,
              "description": "Calls without this argument are rejected (422).",
              "title": "Required",
              "type": "boolean"
            },
            "type": {
              "$ref": "#/$defs/ParamType",
              "description": "JSON type the agent must supply."
            }
          },
          "required": [
            "name",
            "type"
          ],
          "title": "ToolParam",
          "type": "object"
        },
        "ToolSpec": {
          "description": "One tool: typed parameters, optional rules, then ONE SQL statement (parameters bound as %(name)s; use\nRETURNING to send rows back). Runs as the trial's writer role: it can change this environment's tables only.",
          "properties": {
            "description": {
              "description": "What the tool does, shown to the agent in the tool catalog.",
              "title": "Description",
              "type": "string"
            },
            "idempotent": {
              "default": false,
              "description": "Adds an `idempotency_key` argument; a repeated key replays the first response without re-running.",
              "title": "Idempotent",
              "type": "boolean"
            },
            "mutates": {
              "default": true,
              "description": "False for read-only tools; they are still recorded in the ledger but never committed.",
              "title": "Mutates",
              "type": "boolean"
            },
            "name": {
              "description": "Tool name the agent calls; lowercase letters, digits and `_`.",
              "title": "Name",
              "type": "string"
            },
            "params": {
              "default": [],
              "description": "Typed arguments the tool accepts.",
              "items": {
                "$ref": "#/$defs/ToolParam"
              },
              "title": "Params",
              "type": "array"
            },
            "returns": {
              "default": "row",
              "description": "Response shape: `row` is the first row (404 when none), `rows` is a list, `none` is `{}`.",
              "enum": [
                "row",
                "rows",
                "none"
              ],
              "title": "Returns",
              "type": "string"
            },
            "rules": {
              "default": [],
              "description": "Preconditions checked in order before the SQL runs.",
              "items": {
                "$ref": "#/$defs/Rule"
              },
              "title": "Rules",
              "type": "array"
            },
            "sql": {
              "description": "The single SQL statement to run; add RETURNING to send rows back.",
              "title": "Sql",
              "type": "string"
            },
            "success_status": {
              "default": 200,
              "description": "HTTP status returned on success.",
              "maximum": 299,
              "minimum": 200,
              "title": "Success Status",
              "type": "integer"
            }
          },
          "required": [
            "name",
            "description",
            "sql"
          ],
          "title": "ToolSpec",
          "type": "object"
        }
      },
      "description": "A versioned environment: the tables and tools of one simulated world.",
      "properties": {
        "description": {
          "description": "The world in plain English; also given to agents as context.",
          "title": "Description",
          "type": "string"
        },
        "id": {
          "description": "Environment id: 1-64 lowercase letters, digits, `.`, `_` or `-`.",
          "title": "Id",
          "type": "string"
        },
        "tables": {
          "description": "Tables created for every trial; names are unique.",
          "items": {
            "$ref": "#/$defs/Table"
          },
          "minItems": 1,
          "title": "Tables",
          "type": "array"
        },
        "tools": {
          "description": "Tools the agent can call; names are unique.",
          "items": {
            "$ref": "#/$defs/ToolSpec"
          },
          "minItems": 1,
          "title": "Tools",
          "type": "array"
        },
        "version": {
          "description": "Bumped whenever the spec changes; scenarios pin `id@version`.",
          "minimum": 1,
          "title": "Version",
          "type": "integer"
        }
      },
      "required": [
        "id",
        "version",
        "description",
        "tables",
        "tools"
      ],
      "title": "EnvironmentSpec",
      "type": "object"
    }
    ```


## Example: `environments/pharmacy.yaml`

```yaml title="environments/pharmacy.yaml"
id: pharmacy
version: 2
description: A pharmacy prescription system. Each prescription belongs to a patient
  and has a limited number of refills remaining. Controlled-substance prescriptions
  need pharmacist approval before they can be refilled. Placing a refill uses up one
  refill on the prescription and creates a refill order for the pharmacy to fill.
tables:
- name: prescriptions
  columns:
  - name: id
    type: text
    primary_key: true
    nullable: true
    unique: false
    serial: false
    references: null
  - name: patient_name
    type: text
    primary_key: false
    nullable: false
    unique: false
    serial: false
    references: null
  - name: medication
    type: text
    primary_key: false
    nullable: false
    unique: false
    serial: false
    references: null
  - name: controlled
    type: boolean
    primary_key: false
    nullable: false
    unique: false
    serial: false
    references: null
  - name: refills_remaining
    type: integer
    primary_key: false
    nullable: false
    unique: false
    serial: false
    references: null
  - name: pharmacist_approved
    type: boolean
    primary_key: false
    nullable: false
    unique: false
    serial: false
    references: null
- name: refills
  columns:
  - name: id
    type: integer
    primary_key: true
    nullable: true
    unique: false
    serial: true
    references: null
  - name: prescription_id
    type: text
    primary_key: false
    nullable: false
    unique: false
    serial: false
    references: prescriptions.id
  - name: status
    type: text
    primary_key: false
    nullable: false
    unique: false
    serial: false
    references: null
tools:
- name: find_prescriptions
  description: List all prescriptions for a patient by full name, including medication,
    refills remaining, whether it is controlled and whether a pharmacist has approved
    it.
  params:
  - name: patient_name
    type: string
    description: Patient's full name
    required: true
    enum: null
  rules: []
  sql: SELECT * FROM prescriptions WHERE patient_name = %(patient_name)s ORDER BY
    id
  returns: rows
  success_status: 200
  idempotent: false
  mutates: false
- name: get_prescription
  description: Look up one prescription by id, including refills remaining, controlled
    flag and pharmacist approval.
  params:
  - name: prescription_id
    type: string
    description: ''
    required: true
    enum: null
  rules: []
  sql: SELECT * FROM prescriptions WHERE id = %(prescription_id)s
  returns: row
  success_status: 200
  idempotent: false
  mutates: false
- name: get_refills
  description: List the refill orders already placed for a prescription.
  params:
  - name: prescription_id
    type: string
    description: ''
    required: true
    enum: null
  rules: []
  sql: SELECT * FROM refills WHERE prescription_id = %(prescription_id)s ORDER BY
    id
  returns: rows
  success_status: 200
  idempotent: false
  mutates: false
- name: place_refill
  description: Place one refill order for a prescription and use up one remaining
    refill. Fails if no refills remain or a controlled prescription has not been approved
    by a pharmacist. Returns the refill order.
  params:
  - name: prescription_id
    type: string
    description: ''
    required: true
    enum: null
  rules:
  - sql: SELECT NOT EXISTS (SELECT 1 FROM prescriptions WHERE id = %(prescription_id)s)
    status: 404
    error: prescription not found
  - sql: SELECT refills_remaining <= 0 FROM prescriptions WHERE id = %(prescription_id)s
    status: 409
    error: no refills remaining
  - sql: SELECT controlled AND NOT pharmacist_approved FROM prescriptions WHERE id
      = %(prescription_id)s
    status: 403
    error: controlled prescription requires pharmacist approval
  sql: WITH rx AS (UPDATE prescriptions SET refills_remaining = refills_remaining
    - 1 WHERE id = %(prescription_id)s RETURNING id) INSERT INTO refills (prescription_id,
    status) SELECT id, 'placed' FROM rx RETURNING id AS refill_id, prescription_id,
    status
  returns: row
  success_status: 201
  idempotent: true
  mutates: true
```
