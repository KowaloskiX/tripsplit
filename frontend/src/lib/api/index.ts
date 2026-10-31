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
  authLoginMutation,
  authLogoutMutation,
  authRegisterMutation,
  authSessionOptions,
  authSessionQueryKey,
  contributionsPayMutation,
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
  BookingKind,
  ContributionResponse,
  ContributionStatus,
  CreateTripRequest,
  CurrentUserResponse,
  ErrorResponse,
  EventActor,
  EventKind,
  EventResponse,
  HealthStatus,
  LoginRequest,
  MemberResponse,
  MemberRole,
  OrganizationSummary,
  ProposalItemResponse,
  ProposalResponse,
  RegisterRequest,
  Role,
  RoomResponse,
  SessionResponse,
  TripResponse,
  TripStatus,
  TripSummaryResponse,
} from "./generated/types.gen";
