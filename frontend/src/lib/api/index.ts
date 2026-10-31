/**
 * Public surface of the API client.
 *
 * `./generated/` is produced from `../backend/openapi.json`
 * (`pnpm --filter web generate:api`) and is NOT edited by hand. The rest of the application
 * imports from this file only — enforced by dependency-cruiser
 * (`generated-api-client-is-private`).
 */

export {
  type ApiFailure,
  configureApiClient,
  isStaleCsrfToken,
  isUnattendedFailure,
  isUnauthorized,
} from "./client";
export { apiErrorMessage } from "./errors";
export {
  agentRunsStatusOptions,
  authLoginMutation,
  authLogoutMutation,
  authRegisterMutation,
  authSessionOptions,
  authSessionQueryKey,
  bookingsApproveMutation,
  bookingsListOptions,
  bookingsListQueryKey,
  bookingsStartMutation,
  contributionsPayMutation,
  demoDisruptionMutation,
  demoPayAllMutation,
  demoSeedMembersMutation,
  demoVoteAllMutation,
  healthGetOptions,
  proposalsCloseVotingMutation,
  proposalsGenerateMutation,
  proposalsVoteMutation,
  tripsCreateMutation,
  tripsFeedOptions,
  tripsFeedQueryKey,
  tripsJoinMutation,
  tripsListOptions,
  tripsListQueryKey,
  tripsPostMessageMutation,
  tripsRoomOptions,
  tripsRoomQueryKey,
} from "./generated/@tanstack/react-query.gen";
export type {
  AgentOutcome,
  AgentRunResponse,
  BookingKind,
  BookingResponse,
  BookingStatus,
  ContributionResponse,
  ContributionStatus,
  CreateTripRequest,
  CurrentUserResponse,
  DisruptionResponse,
  ErrorResponse,
  EventActor,
  EventKind,
  EventResponse,
  HealthStatus,
  LiveStatusResponse,
  LoginRequest,
  MemberResponse,
  MemberRole,
  OrganizationSummary,
  ProposalItemResponse,
  ProposalResponse,
  RegisterRequest,
  Role,
  RoomResponse,
  RunStatusResponse,
  SessionResponse,
  ShareChangeResponse,
  TripBookingsResponse,
  TripResponse,
  TripStatus,
  TripSummaryResponse,
} from "./generated/types.gen";

/**
 * The newest frame of an agent run, for an `<img src>`. A binary response is not something the
 * generated JSON client can hand to an image tag, so the URL is built here — next to the client
 * that owns the API's paths — rather than in a feature. `tick` busts the browser cache.
 */
export function agentRunFrameUrl(runId: string, tick: number): string {
  return `/api/agent-runs/${encodeURIComponent(runId)}/frame?t=${tick}`;
}
