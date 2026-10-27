import assert from "node:assert/strict";
import test from "node:test";
import { youtubeOAuthFeedback } from "./youtube-oauth.mjs";

test("OAuth failure codes always render destructive feedback", () => {
  for (const code of [
    "oauth_state_invalid", "oauth_token_exchange_failed", "oauth_scope_insufficient",
    "oauth_scope_verification_failed", "oauth_scope_downgrade_blocked", "oauth_account_unavailable",
    "youtube_channel_mismatch", "analytics_scope_missing",
    "youtube_channel_not_found", "youtube_api_failed", "oauth_token_storage_failed",
    "oauth_redirect_uri_mismatch", "oauth_code_rejected", "oauth_connection_failed",
    "error", "state_error", "oauth_error", "unknown-result",
  ]) {
    const feedback = youtubeOAuthFeedback(code);
    assert.equal(feedback.kind, "error", code);
    assert.equal(feedback.className, "notice notice-error accounts-oauth-feedback", code);
    assert.equal(feedback.role, "alert", code);
    assert.ok(feedback.message.length > 0, code);
  }
});

test("OAuth success and cancellation use distinct non-error styles", () => {
  assert.equal(youtubeOAuthFeedback("connected").className, "notice notice-success accounts-oauth-feedback");
  assert.equal(youtubeOAuthFeedback("analytics_enabled").kind, "success");
  assert.equal(youtubeOAuthFeedback("connected_analytics_scope_missing").kind, "info");
  assert.equal(youtubeOAuthFeedback("oauth_cancelled").className, "notice notice-info accounts-oauth-feedback");
});
