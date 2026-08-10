/**
 * CMP-owned auth bootstrap shapes (AUTH-001B2). Deliberately NOT the raw
 * Auth0 SDK session/user shape and NOT a 1:1 re-export of the generated
 * `AuthMeRead` -- this is the one contract both server (route handlers)
 * and client (provider/hooks) code import, so nothing downstream ever
 * needs to know whether a given field came from Auth0 or from FastAPI.
 */

export type AuthBootstrapStatus = "authenticated" | "unauthenticated" | "not_provisioned" | "error";

export interface TenantMembership {
  tenantId: string;
  tenantCode: string;
  tenantName: string;
  roleCode: string;
}

export interface AuthBootstrapUser {
  id: string;
  email: string;
  displayName: string;
}

export interface AuthBootstrap {
  status: AuthBootstrapStatus;
  user: AuthBootstrapUser | null;
  memberships: TenantMembership[];
  /** The tenant the BFF has reconciled as active -- already verified
   * against the fresh membership list that produced this same bootstrap
   * object. Never trust a client-cached value against a *different*
   * bootstrap response. */
  selectedTenantId: string | null;
}
