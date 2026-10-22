// ==========================================================================
// GENERATED FILE — DO NOT EDIT BY HAND.
// Regenerate with `pnpm --filter @candleviewer/protocol generate`.
// Source: services/api/candleviewer/rules/ir/rule-ir.json, the JSON Schema that
// `GET /api/v1/schemas/rule-ir.json` serves, rendered from
// services/api/candleviewer/rules/ir/models.py by
// services/api/scripts/generate_rule_ir_schema.py. Hand edits are rejected by
// the header-guard lint (packages/protocol/scripts/check-generated-guard.mjs).
// ==========================================================================
/* eslint-disable */

export type Notional = number | string;

export interface RuleIr {
  /**
   * @minItems 1
   * @maxItems 10
   */
  actions:
    | [Action]
    | [Action, Action]
    | [Action, Action, Action]
    | [Action, Action, Action, Action]
    | [Action, Action, Action, Action, Action]
    | [Action, Action, Action, Action, Action, Action]
    | [Action, Action, Action, Action, Action, Action, Action]
    | [Action, Action, Action, Action, Action, Action, Action, Action]
    | [Action, Action, Action, Action, Action, Action, Action, Action, Action]
    | [Action, Action, Action, Action, Action, Action, Action, Action, Action, Action];
  conditions: Comparison | BooleanNode | TemporalNode;
  created_at?: number | null;
  created_by?: string | null;
  description?: string;
  editor?: "form" | "graph";
  enabled: boolean;
  graph_layout?: {
    [k: string]: unknown;
  } | null;
  ir_version?: 1;
  limits?: RuleLimits;
  mode: "disabled" | "simulate" | "armed";
  name: string;
  rule_id: string;
  scope: RuleScope;
  trigger: Trigger;
  updated_at?: number | null;
  version: number;
}
export interface Action {
  dry_run_only?: boolean;
  node_id: string;
  on_error?: "abort_remaining" | "continue" | "retry_once";
  params: {
    [k: string]: unknown;
  };
  targets?: "scope_accounts" | "originating_account" | "all_accounts";
  type:
    | "place_order"
    | "modify_stop_loss"
    | "modify_take_profit"
    | "cancel_order"
    | "cancel_all_orders"
    | "move_to_breakeven"
    | "scale_out"
    | "scale_in"
    | "flatten_position"
    | "flatten_all_positions"
    | "reverse_position"
    | "halt_new_orders"
    | "resume_new_orders"
    | "reduce_leverage"
    | "widen_stop"
    | "tighten_stop"
    | "arm_chase_limit"
    | "start_iceberg_slice"
    | "start_twap"
    | "send_notification"
    | "log_journal_tag"
    | "set_variable"
    | "emit_signal"
    | "pause_rule"
    | "enable_rule";
}
export interface Comparison {
  left: MetricRef | Literal_ | ArithmeticNode;
  node_id: string;
  op:
    | "gt"
    | "gte"
    | "lt"
    | "lte"
    | "eq"
    | "neq"
    | "between"
    | "outside"
    | "crosses_above"
    | "crosses_below"
    | "changed"
    | "is_true"
    | "is_false"
    | "in_set"
    | "not_in_set";
  right?: (MetricRef | Literal_ | ArithmeticNode) | null;
  right2?: (MetricRef | Literal_ | ArithmeticNode) | null;
  set_values?: string[];
  tolerance?: number | string | null;
}
export interface MetricRef {
  account_id?: string | null;
  metric: string;
  params?: {
    [k: string]: boolean | number | string | null;
  };
  symbol?: string | null;
  timeframe?: string | null;
}
/**
 * Constant operand; ``{"const": ...}`` in JSON.
 */
export interface Literal_ {
  const: boolean | number | string;
}
export interface ArithmeticNode {
  node_id: string;
  op: "add" | "sub" | "mul" | "div" | "abs" | "min" | "max" | "neg" | "pct_of";
  /**
   * @minItems 1
   * @maxItems 8
   */
  operands:
    | [MetricRef | Literal_ | ArithmeticNode]
    | [MetricRef | Literal_ | ArithmeticNode, MetricRef | Literal_ | ArithmeticNode]
    | [
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
      ]
    | [
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
      ]
    | [
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
      ]
    | [
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
      ]
    | [
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
      ]
    | [
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
        MetricRef | Literal_ | ArithmeticNode,
      ];
}
export interface BooleanNode {
  /**
   * @minItems 1
   * @maxItems 32
   */
  children: [
    Comparison | BooleanNode | TemporalNode,
    ...(Comparison | BooleanNode | TemporalNode)[],
  ];
  n?: number | null;
  node_id: string;
  op: "all_of" | "any_of" | "none_of" | "n_of";
}
export interface TemporalNode {
  child: Comparison | BooleanNode | TemporalNode;
  min_count?: number;
  node_id: string;
  op: "sustained_for" | "occurred_within" | "count_within" | "stable_for";
  window_ms: number;
}
export interface RuleLimits {
  cooldown_ms?: number;
  evaluation_timeout_ms?: number;
  kill_switch_on_error_count?: number;
  max_actions_per_fire?: number;
  max_daily_notional?: Notional | null;
  max_fires_per_day?: number;
  max_fires_per_hour?: number;
  max_notional_per_fire?: Notional | null;
  once?: boolean;
  once_per?: ("position" | "day" | "group" | "rule_lifetime") | null;
  require_confirmation?: boolean;
}
export interface RuleScope {
  account_ids?: string[];
  applies_to?: "open_positions" | "pending_orders" | "account" | "any";
  environments?: ("live" | "demo" | "testnet")[];
  exclude_algo_children?: boolean;
  level: "global" | "account" | "symbol" | "position" | "trade_group";
  symbols?: string[];
}
export interface Trigger {
  cron?: string | null;
  debounce_ms?: number;
  interval_ms?: number | null;
  metric?: string | null;
  timeframe?: string | null;
  type:
    | "on_price_update"
    | "on_bar_close"
    | "on_order_fill"
    | "on_position_open"
    | "on_position_close"
    | "on_position_update"
    | "on_timer"
    | "on_metric_change"
    | "on_signal"
    | "on_schedule"
    | "pre_trade_check"
    | "on_book_update"
    | "on_liquidation";
}

export const RULE_IR_SCHEMA_ID = "https://candleviewer.local/schemas/rule-ir-v1.json";

// Freezes a value and everything reachable from it (plain JSON: no cycles).
function deepFreeze<T>(value: T): T {
  if (typeof value === "object" && value !== null) {
    for (const child of Object.values(value)) deepFreeze(child);
    Object.freeze(value);
  }
  return value;
}

/**
 * The published schema, verbatim; the canonical mirror reads defaults and field kinds from it.
 * Frozen at every depth, so no consumer can change what another reads.
 */
export const RULE_IR_SCHEMA: { readonly [key: string]: unknown } = deepFreeze({
  $defs: {
    Action: {
      additionalProperties: false,
      properties: {
        dry_run_only: { default: false, title: "Dry Run Only", type: "boolean" },
        node_id: { title: "Node Id", type: "string" },
        on_error: {
          default: "abort_remaining",
          enum: ["abort_remaining", "continue", "retry_once"],
          title: "On Error",
          type: "string",
        },
        params: { additionalProperties: true, title: "Params", type: "object" },
        targets: {
          default: "scope_accounts",
          enum: ["scope_accounts", "originating_account", "all_accounts"],
          title: "Targets",
          type: "string",
        },
        type: {
          enum: [
            "place_order",
            "modify_stop_loss",
            "modify_take_profit",
            "cancel_order",
            "cancel_all_orders",
            "move_to_breakeven",
            "scale_out",
            "scale_in",
            "flatten_position",
            "flatten_all_positions",
            "reverse_position",
            "halt_new_orders",
            "resume_new_orders",
            "reduce_leverage",
            "widen_stop",
            "tighten_stop",
            "arm_chase_limit",
            "start_iceberg_slice",
            "start_twap",
            "send_notification",
            "log_journal_tag",
            "set_variable",
            "emit_signal",
            "pause_rule",
            "enable_rule",
          ],
          title: "Type",
          type: "string",
        },
      },
      required: ["node_id", "type", "params"],
      title: "Action",
      type: "object",
    },
    ArithmeticNode: {
      additionalProperties: false,
      properties: {
        node_id: { title: "Node Id", type: "string" },
        op: {
          enum: ["add", "sub", "mul", "div", "abs", "min", "max", "neg", "pct_of"],
          title: "Op",
          type: "string",
        },
        operands: {
          items: {
            oneOf: [
              { $ref: "#/$defs/MetricRef" },
              { $ref: "#/$defs/Literal_" },
              { $ref: "#/$defs/ArithmeticNode" },
            ],
          },
          maxItems: 8,
          minItems: 1,
          title: "Operands",
          type: "array",
        },
      },
      required: ["node_id", "op", "operands"],
      title: "ArithmeticNode",
      type: "object",
    },
    BooleanNode: {
      additionalProperties: false,
      properties: {
        children: {
          items: {
            oneOf: [
              { $ref: "#/$defs/Comparison" },
              { $ref: "#/$defs/BooleanNode" },
              { $ref: "#/$defs/TemporalNode" },
            ],
          },
          maxItems: 32,
          minItems: 1,
          title: "Children",
          type: "array",
        },
        n: {
          anyOf: [{ minimum: 1, type: "integer" }, { type: "null" }],
          default: null,
          title: "N",
        },
        node_id: { title: "Node Id", type: "string" },
        op: { enum: ["all_of", "any_of", "none_of", "n_of"], title: "Op", type: "string" },
      },
      required: ["node_id", "op", "children"],
      title: "BooleanNode",
      type: "object",
    },
    Comparison: {
      additionalProperties: false,
      properties: {
        left: {
          oneOf: [
            { $ref: "#/$defs/MetricRef" },
            { $ref: "#/$defs/Literal_" },
            { $ref: "#/$defs/ArithmeticNode" },
          ],
          title: "Left",
        },
        node_id: { title: "Node Id", type: "string" },
        op: {
          enum: [
            "gt",
            "gte",
            "lt",
            "lte",
            "eq",
            "neq",
            "between",
            "outside",
            "crosses_above",
            "crosses_below",
            "changed",
            "is_true",
            "is_false",
            "in_set",
            "not_in_set",
          ],
          title: "Op",
          type: "string",
        },
        right: {
          anyOf: [
            {
              oneOf: [
                { $ref: "#/$defs/MetricRef" },
                { $ref: "#/$defs/Literal_" },
                { $ref: "#/$defs/ArithmeticNode" },
              ],
            },
            { type: "null" },
          ],
          default: null,
          title: "Right",
        },
        right2: {
          anyOf: [
            {
              oneOf: [
                { $ref: "#/$defs/MetricRef" },
                { $ref: "#/$defs/Literal_" },
                { $ref: "#/$defs/ArithmeticNode" },
              ],
            },
            { type: "null" },
          ],
          default: null,
          title: "Right2",
        },
        set_values: { default: [], items: { type: "string" }, title: "Set Values", type: "array" },
        tolerance: {
          anyOf: [
            { type: "number" },
            { pattern: "^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$", type: "string" },
            { type: "null" },
          ],
          default: null,
          title: "Tolerance",
        },
      },
      required: ["node_id", "op", "left"],
      title: "Comparison",
      type: "object",
    },
    Literal_: {
      additionalProperties: false,
      description: 'Constant operand; ``{"const": ...}`` in JSON.',
      properties: {
        const: {
          anyOf: [
            { type: "boolean" },
            { type: "integer" },
            { type: "number" },
            { pattern: "^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$", type: "string" },
            { type: "string" },
          ],
          title: "Const",
        },
      },
      required: ["const"],
      title: "Literal_",
      type: "object",
    },
    MetricRef: {
      additionalProperties: false,
      properties: {
        account_id: {
          anyOf: [{ format: "uuid", type: "string" }, { type: "null" }],
          default: null,
          title: "Account Id",
        },
        metric: { pattern: "^[a-z][a-z0-9_]{1,48}$", title: "Metric", type: "string" },
        params: {
          additionalProperties: {
            anyOf: [
              { type: "boolean" },
              { type: "integer" },
              { type: "number" },
              { pattern: "^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$", type: "string" },
              { type: "string" },
              { type: "null" },
            ],
          },
          title: "Params",
          type: "object",
        },
        symbol: {
          anyOf: [{ pattern: "^[A-Z0-9]{4,20}$", type: "string" }, { type: "null" }],
          default: null,
          title: "Symbol",
        },
        timeframe: {
          anyOf: [{ type: "string" }, { type: "null" }],
          default: null,
          title: "Timeframe",
        },
      },
      required: ["metric"],
      title: "MetricRef",
      type: "object",
    },
    Notional: {
      anyOf: [{ type: "number" }, { pattern: "^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$", type: "string" }],
    },
    RuleLimits: {
      additionalProperties: false,
      properties: {
        cooldown_ms: { default: 1000, minimum: 0, title: "Cooldown Ms", type: "integer" },
        evaluation_timeout_ms: {
          default: 250,
          maximum: 5000,
          minimum: 10,
          title: "Evaluation Timeout Ms",
          type: "integer",
        },
        kill_switch_on_error_count: {
          default: 5,
          minimum: 1,
          title: "Kill Switch On Error Count",
          type: "integer",
        },
        max_actions_per_fire: {
          default: 10,
          maximum: 10,
          minimum: 1,
          title: "Max Actions Per Fire",
          type: "integer",
        },
        max_daily_notional: {
          anyOf: [{ $ref: "#/$defs/Notional" }, { type: "null" }],
          default: null,
        },
        max_fires_per_day: {
          default: 500,
          minimum: 1,
          title: "Max Fires Per Day",
          type: "integer",
        },
        max_fires_per_hour: {
          default: 60,
          minimum: 1,
          title: "Max Fires Per Hour",
          type: "integer",
        },
        max_notional_per_fire: {
          anyOf: [{ $ref: "#/$defs/Notional" }, { type: "null" }],
          default: null,
        },
        once: { default: false, title: "Once", type: "boolean" },
        once_per: {
          anyOf: [
            { enum: ["position", "day", "group", "rule_lifetime"], type: "string" },
            { type: "null" },
          ],
          default: null,
          title: "Once Per",
        },
        require_confirmation: { default: false, title: "Require Confirmation", type: "boolean" },
      },
      title: "RuleLimits",
      type: "object",
    },
    RuleScope: {
      additionalProperties: false,
      properties: {
        account_ids: {
          default: [],
          items: { format: "uuid", type: "string" },
          title: "Account Ids",
          type: "array",
        },
        applies_to: {
          default: "any",
          enum: ["open_positions", "pending_orders", "account", "any"],
          title: "Applies To",
          type: "string",
        },
        environments: {
          default: ["demo"],
          items: { enum: ["live", "demo", "testnet"], type: "string" },
          title: "Environments",
          type: "array",
        },
        exclude_algo_children: { default: true, title: "Exclude Algo Children", type: "boolean" },
        level: {
          enum: ["global", "account", "symbol", "position", "trade_group"],
          title: "Level",
          type: "string",
        },
        symbols: {
          default: [],
          items: { pattern: "^[A-Z0-9]{4,20}$", type: "string" },
          title: "Symbols",
          type: "array",
        },
      },
      required: ["level"],
      title: "RuleScope",
      type: "object",
    },
    TemporalNode: {
      additionalProperties: false,
      properties: {
        child: {
          oneOf: [
            { $ref: "#/$defs/Comparison" },
            { $ref: "#/$defs/BooleanNode" },
            { $ref: "#/$defs/TemporalNode" },
          ],
          title: "Child",
        },
        min_count: { default: 1, minimum: 1, title: "Min Count", type: "integer" },
        node_id: { title: "Node Id", type: "string" },
        op: {
          enum: ["sustained_for", "occurred_within", "count_within", "stable_for"],
          title: "Op",
          type: "string",
        },
        window_ms: { maximum: 86400000, minimum: 100, title: "Window Ms", type: "integer" },
      },
      required: ["node_id", "op", "child", "window_ms"],
      title: "TemporalNode",
      type: "object",
    },
    Trigger: {
      additionalProperties: false,
      allOf: [
        {
          if: { properties: { type: { const: "on_timer" } } },
          then: { required: ["interval_ms"] },
        },
        {
          if: { properties: { type: { const: "on_bar_close" } } },
          then: { required: ["timeframe"] },
        },
        { if: { properties: { type: { const: "on_schedule" } } }, then: { required: ["cron"] } },
        {
          if: { properties: { type: { const: "on_metric_change" } } },
          then: { required: ["metric"] },
        },
      ],
      properties: {
        cron: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Cron" },
        debounce_ms: { default: 0, minimum: 0, title: "Debounce Ms", type: "integer" },
        interval_ms: {
          anyOf: [{ minimum: 100, type: "integer" }, { type: "null" }],
          default: null,
          title: "Interval Ms",
        },
        metric: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Metric" },
        timeframe: {
          anyOf: [{ type: "string" }, { type: "null" }],
          default: null,
          title: "Timeframe",
        },
        type: {
          enum: [
            "on_price_update",
            "on_bar_close",
            "on_order_fill",
            "on_position_open",
            "on_position_close",
            "on_position_update",
            "on_timer",
            "on_metric_change",
            "on_signal",
            "on_schedule",
            "pre_trade_check",
            "on_book_update",
            "on_liquidation",
          ],
          title: "Type",
          type: "string",
        },
      },
      required: ["type"],
      title: "Trigger",
      type: "object",
    },
  },
  $id: "https://candleviewer.local/schemas/rule-ir-v1.json",
  $schema: "https://json-schema.org/draft/2020-12/schema",
  additionalProperties: false,
  properties: {
    actions: {
      items: { $ref: "#/$defs/Action" },
      maxItems: 10,
      minItems: 1,
      title: "Actions",
      type: "array",
    },
    conditions: {
      oneOf: [
        { $ref: "#/$defs/Comparison" },
        { $ref: "#/$defs/BooleanNode" },
        { $ref: "#/$defs/TemporalNode" },
      ],
      title: "Conditions",
    },
    created_at: {
      anyOf: [{ type: "integer" }, { type: "null" }],
      default: null,
      title: "Created At",
    },
    created_by: {
      anyOf: [{ format: "uuid", type: "string" }, { type: "null" }],
      default: null,
      title: "Created By",
    },
    description: { default: "", maxLength: 2000, title: "Description", type: "string" },
    editor: { default: "form", enum: ["form", "graph"], title: "Editor", type: "string" },
    enabled: { title: "Enabled", type: "boolean" },
    graph_layout: {
      anyOf: [{ additionalProperties: true, type: "object" }, { type: "null" }],
      default: null,
      title: "Graph Layout",
    },
    ir_version: { const: 1, default: 1, title: "Ir Version", type: "integer" },
    limits: { $ref: "#/$defs/RuleLimits" },
    mode: { enum: ["disabled", "simulate", "armed"], title: "Mode", type: "string" },
    name: { maxLength: 120, minLength: 1, title: "Name", type: "string" },
    rule_id: { format: "uuid", title: "Rule Id", type: "string" },
    scope: { $ref: "#/$defs/RuleScope" },
    trigger: { $ref: "#/$defs/Trigger" },
    updated_at: {
      anyOf: [{ type: "integer" }, { type: "null" }],
      default: null,
      title: "Updated At",
    },
    version: { minimum: 1, title: "Version", type: "integer" },
  },
  required: [
    "rule_id",
    "version",
    "name",
    "enabled",
    "mode",
    "scope",
    "trigger",
    "conditions",
    "actions",
  ],
  title: "CandleViewer Rule IR",
  type: "object",
});
