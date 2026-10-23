// Short names for the API's response and request types. They all come from schema.d.ts,
// which is generated from the FastAPI OpenAPI schema (npm run gen:types), so the dashboard's
// idea of every response is exactly the API's own definition.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type RunSummary = Schemas["RunSummary"];
export type RunStatus = RunSummary["status"];
export type RunDetail = Schemas["RunDetail"];
export type Metrics = Schemas["Metrics"];
export type StrategyMetrics = Schemas["StrategyMetrics"];
export type BenchmarkMetrics = Schemas["BenchmarkMetrics"];
export type BenchmarkNotComputed = Schemas["BenchmarkNotComputed"];
export type Ratio = Schemas["Ratio"];
export type YearRow = Schemas["YearRow"];
export type MonthRow = Schemas["MonthRow"];
export type TradeRecord = Schemas["TradeRecord"];
export type TradeDetail = Schemas["TradeDetail"];
export type MarkRow = Schemas["MarkRow"];
export type EquityPoint = Schemas["EquityPoint"];
export type DailyPoint = Schemas["DailyPoint"];
export type SkippedWeek = Schemas["SkippedWeek"];
export type ErrorBody = Schemas["ErrorBody"];
export type RunRequest = Schemas["RunRequest"];
