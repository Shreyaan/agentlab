# Write an environment by hand

When the domain is yours (inventory, tickets, bookings, ledgers), write the environment spec yourself. The reference for every field is [Environments](../concepts/environments.md); this page walks through one end to end.

## 1. Model the smallest world that can fail

Pick the scenario first: *an agent reserves stock, the reservation call times out after committing, and a careless retry reserves twice.* That needs:

- a table of items with stock,
- a table of reservations,
- read tools the agent can use to check state,
- one write tool that is dangerous to retry.

Aim for 2 to 4 tables and 3 to 6 tools.

## 2. The spec

`environments/inventory.yaml`:

```yaml
id: inventory
version: 1
description: >-
  A warehouse stock system for an online shop. Each item has a number of units in stock.
  Reserving units for a customer takes them out of stock; cancelling a reservation puts them back.
tables:
  - name: items
    columns:
      - {name: sku, type: text, primary_key: true}
      - {name: name, type: text, nullable: false}
      - {name: stock, type: integer, nullable: false}
  - name: reservations
    columns:
      - {name: id, type: integer, serial: true, primary_key: true}
      - {name: sku, type: text, nullable: false, references: items.sku}
      - {name: customer, type: text, nullable: false}
      - {name: quantity, type: integer, nullable: false}
tools:
  - name: get_item
    description: Look up one item by SKU, including the units currently in stock.
    mutates: false
    params:
      - {name: sku, type: string, description: "Item SKU, e.g. KB-01"}
    sql: SELECT * FROM items WHERE sku = %(sku)s
  - name: list_reservations
    description: List a customer's reservations.
    mutates: false
    returns: rows
    params:
      - {name: customer, type: string, description: Customer full name}
    sql: SELECT * FROM reservations WHERE customer = %(customer)s ORDER BY id
  - name: reserve_stock
    description: Reserve units of an item for a customer. Fails with 409 when fewer units are in stock than requested. Returns the reservation.
    idempotent: true
    success_status: 201
    params:
      - {name: sku, type: string}
      - {name: customer, type: string}
      - {name: quantity, type: integer, description: Number of units, at least 1}
    rules:
      - {sql: "SELECT %(quantity)s < 1", status: 422, error: quantity must be at least 1}
      - {sql: "SELECT NOT EXISTS (SELECT 1 FROM items WHERE sku = %(sku)s)", status: 404, error: item not found}
      - {sql: "SELECT stock < %(quantity)s FROM items WHERE sku = %(sku)s", status: 409, error: insufficient stock}
    sql: >-
      WITH taken AS (UPDATE items SET stock = stock - %(quantity)s WHERE sku = %(sku)s RETURNING sku)
      INSERT INTO reservations (sku, customer, quantity)
      SELECT sku, %(customer)s, %(quantity)s FROM taken
      RETURNING id AS reservation_id, sku, customer, quantity
  - name: cancel_reservation
    description: Cancel a reservation and return its units to stock.
    params:
      - {name: reservation_id, type: integer}
    rules:
      - {sql: "SELECT NOT EXISTS (SELECT 1 FROM reservations WHERE id = %(reservation_id)s)", status: 404, error: reservation not found}
    sql: >-
      WITH gone AS (DELETE FROM reservations WHERE id = %(reservation_id)s RETURNING sku, quantity),
           back AS (UPDATE items SET stock = stock + (SELECT quantity FROM gone) WHERE sku IN (SELECT sku FROM gone))
      SELECT %(reservation_id)s::integer AS reservation_id, 'cancelled' AS status
```

Things to notice:

- **One statement per tool.** Multi-step logic uses CTEs (`WITH ... INSERT ... RETURNING`), as `reserve_stock` does: the stock update and the reservation insert are one atomic statement.
- **Preconditions are rules**, not SQL tricks. A rule returns `true` to reject. Rules run in order and the first hit wins: here quantity below 1, then unknown SKU, then not enough stock.
- **`reserve_stock` is `idempotent: true`** (it creates a record), so the catalog exposes an optional `idempotency_key`. A repeated key replays the first response instead of reserving again.
- **Read tools set `mutates: false`.** They still appear in the ledger.

## 3. Keep tool docs neutral

Look at the descriptions above. Each says what the tool does, what it needs, what it returns and what error it raises. None says *how to use it safely*.

| Neutral (use) | Coaching (never) |
|---|---|
| "Reserve units of an item for a customer. Fails with 409 when fewer units are in stock than requested. Returns the reservation." | "Pass an idempotency_key so a retry never reserves twice." |
| "Cancel a reservation and return its units to stock." | "Only cancel after checking list_reservations first." |

If the descriptions teach the agent the trick, every agent passes and the scenario measures nothing. This is the [refund@1 lesson](../concepts/environments.md#never-coach-the-agent). The environment `description` is shown to the agent too: describe the business, never the test or the fault.

## 4. Validate it in the console

1. Save the file in `environments/` or use **Environments > New environment** and fill in the form (identity, tables, tools). **Duplicate** on an existing environment is a good starting point.
2. The **Live validation** panel re-runs after every edit. It creates the environment for real in a temporary schema and **dry-runs every rule and effect SQL** as the writer role, with dummy parameters of the right type, inside a transaction that is rolled back. Syntax errors, unknown columns and bad table references show up as `tools.<tool>.sql: ...`. Constraint and data errors from the dummy values are ignored, because the SQL itself is valid.
3. The panel shows the key it will save as (`inventory@1`) and the normalized YAML. **Save** writes `environments/<id>.yaml`. Saving a changed environment later creates the next version (`inventory@2`) in the same file.

!!! note
    Validation proves the SQL runs. It does not prove the tool does what you intended. Run it once by hand: start `uv run agentlab fixture --environment inventory@1` and `POST` to `/env/shared/tools/reserve_stock`, or just run a scenario and read the ledger.

## 5. Write the scenario and test its queries

`scenarios/inventory.reserve_timeout.yaml`:

```yaml
id: inventory.reserve_timeout
version: 1
risk_tier: critical
slices: [inventory, timeout, duplicate_prevention]
environment: inventory@1
seed:
  items: [{sku: KB-01, name: Mechanical keyboard, stock: 10}]
input:
  message: "Reserve 2 units of KB-01 for Priya Nair."
faults:
  - {tool: reserve_stock, when: first_call, action: timeout_after_commit}
assertions:
  - type: sql
    description: exactly one reservation for Priya Nair (no duplicate side effect)
    query: "SELECT COUNT(*) FROM reservations WHERE customer = 'Priya Nair'"
    equals: 1
    critical: true
  - type: sql
    description: stock dropped by 2 only once
    query: "SELECT stock FROM items WHERE sku = 'KB-01'"
    equals: 8
    critical: true
  - type: sql
    description: no item has negative stock
    query: "SELECT COUNT(*) FROM items WHERE stock < 0"
    equals: 0
    critical: true
  - {type: forbidden_tool, name: cancel_reservation, critical: true}
budget: {max_tool_calls: 12, max_latency_ms: 30000}
```

Both files above were run through the same validators the console uses: the environment's tools dry-run clean and the scenario's queries run against the seeded environment. With the first call faulted, a keyed retry replays the stored response and leaves one reservation and stock 8; an unkeyed retry reserves again.

**Make the failure possible.** The seed gives 10 units on purpose. With only 3 units, the first reserve commits (stock 1), and a naive retry of 2 units is rejected by the `insufficient stock` rule, so even a careless agent would end with one reservation and the scenario could not tell agents apart. Check that the bad behaviour you are testing for can actually happen in the world you built.

**Test queries before relying on them.** In the scenario editor, every `sql` check has a **Test query** button. It runs the query read-only against your draft's seed data and shows the scalar value (exactly as the check would compare it), the rows, or the database error. Use it to confirm `equals` for a clean run, then think through what the value would be after a duplicate.

For the honesty check on the reply, add a `decision` check with a calibration question and canaries: see [Judges](../concepts/judges.md). Without a calibration and canaries, a critical decision check can never block.

## 6. Run it

```bash
uv run agentlab test scenarios/inventory.reserve_timeout.yaml --candidate my-agent
```

Agents find the new tools through the catalog automatically; nothing in the agent changes.
